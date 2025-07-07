import os
import requests
from bs4 import BeautifulSoup
import re
import asyncio
from playwright.async_api import async_playwright, Browser
import time
import random

# Global variable to hold the Playwright browser instance
_playwright_browser: Browser | None = None

async def initialize_playwright_browser():
    """Initializes a single Playwright browser instance if one isn't already running."""
    global _playwright_browser
    if _playwright_browser is None:
        print("Initializing Playwright browser...")
        p = await async_playwright().start()
        _playwright_browser = await p.chromium.launch(headless=True) 
        print("Playwright browser initialized.")

async def close_playwright_browser():
    """Closes the Playwright browser instance if it's open."""
    global _playwright_browser
    if _playwright_browser:
        print("Closing Playwright browser...")
        await _playwright_browser.close()
        _playwright_browser = None
        print("Playwright browser closed.")

def _scrape_article_links_from_profile(profile_url: str) -> list[str]:
    """
    Scrapes an author's Google Scholar profile page to find direct article links.
    Uses requests; suitable for profile scraping.

    Args:
        profile_url (str): The URL of the Google Scholar author profile page.

    Returns:
        list[str]: A list of unique article URLs found on the profile page.
    """
    article_links = set()
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Introduce a small random delay for direct requests to profile page
        time.sleep(random.uniform(2, 5)) 
        response = requests.get(profile_url, headers=headers, timeout=10) 
        response.raise_for_status() 

        soup = BeautifulSoup(response.text, 'html.parser')

        for link_tag in soup.find_all('a', class_='gsc_a_at'):
            href = link_tag.get('href')
            if href:
                if not href.startswith('http'):
                    full_url = f"https://scholar.google.com{href}"
                else:
                    full_url = href
                
                if "view_article" in full_url: 
                    article_links.add(full_url)
        
        if not article_links:
            print(f"DEBUG: No article links with class 'gsc_a_at' and 'view_article' found on {profile_url}.")

    except requests.exceptions.Timeout:
        print(f"Error: Timeout occurred while scraping profile URL {profile_url}. The server took too long to respond.")
    except requests.exceptions.RequestException as e:
        print(f"Error scraping profile URL {profile_url}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during profile scraping: {e}")

    return sorted(list(article_links))


async def _get_page_content_and_description(url: str) -> tuple[str | None, str | None]:
    """
    Fetches the HTML content of a Google Scholar article detail page using Playwright
    and attempts to extract the article's abstract/description.
    Reuses an existing Playwright browser instance.

    Args:
        url (str): The URL of the Google Scholar article detail webpage.

    Returns:
        tuple[str | None, str | None]: A tuple containing the HTML content and the extracted description,
                                        or (None, None) if an error occurred or description not found.
    """
    html_content = None
    description_text = None

    try:
        if _playwright_browser is None:
            await initialize_playwright_browser()

        page = await _playwright_browser.new_page()
        
        # Introduce a delay before navigating with Playwright to mitigate rate limits
        await asyncio.sleep(random.uniform(5, 10)) 
        await page.goto(url, wait_until='networkidle', timeout=60000) # Increased timeout
        
        html_content = await page.content()
        await page.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        
        # PRIMARY ATTEMPT: Target the precise structure from your screenshot
        description_container_div = soup.find('div', id='gsc_oci_descr')
        if description_container_div:
            description_content_div = description_container_div.find('div', class_='gsh_small')
            if description_content_div:
                description_text = description_content_div.get_text(separator=' ', strip=True)
                if len(description_text) > 50: # Ensure it's a substantial description
                    print(f"DEBUG: Found description using 'gsc_oci_descr' and 'gsh_small' for {url}")
                    return html_content, description_text

        # Fallback 1: For older or different Google Scholar article page types
        description_label_div_vcd = soup.find('div', class_='gsc_vcd_field', string='Description')
        if description_label_div_vcd:
            description_content_div_vcd = description_label_div_vcd.find_next_sibling('div', class_='gsc_vcd_value')
            if description_content_div_vcd:
                description_text = description_content_div_vcd.get_text(separator=' ', strip=True)
                if len(description_text) > 50: 
                    print(f"DEBUG: Found description using 'gsc_vcd_field' + 'gsc_vcd_value' (fallback) for {url}")
                    return html_content, description_text

        # Fallback 2: General ID (less common for full description block)
        description_div_by_id = soup.find('div', id='gsc_vcd_descr') 
        if description_div_by_id:
            description_text = description_div_by_id.get_text(separator=' ', strip=True)
            if len(description_text) > 50:
                print(f"DEBUG: Found description using id='gsc_vcd_descr' (fallback) for {url}")
                return html_content, description_text

        # Fallback 3: Blockquote (might be abstract, might be a quote)
        blockquote_tags = soup.find_all('blockquote')
        for bq in blockquote_tags:
            text = bq.get_text(separator=' ', strip=True)
            if len(text) > 50:
                description_text = text
                print(f"DEBUG: Found description using blockquote tag (fallback) for {url}")
                return html_content, description_text

        # Fallback 4: Regex for common class names (least precise, last resort)
        possible_description_divs = soup.find_all('div', class_=re.compile(r'abstract|description|snippet|gsc_vcd_content', re.IGNORECASE))
        for div in possible_description_divs:
            text = div.get_text(separator=' ', strip=True)
            if len(text) > 50:
                description_text = text
                print(f"DEBUG: Found description using a common class name (LAST RESORT fallback) for {url}")
                return html_content, description_text
        
        # Fallback 5: Meta description tag (often too short for full abstract)
        meta_description = soup.find('meta', attrs={'name': 'description'})
        if meta_description and meta_description.get('content'):
            description_text = meta_description.get('content').strip()
            if len(description_text) > 50:
                print(f"DEBUG: Found description using meta description tag (fallback) for {url}")
                return html_content, description_text

        print(f"DEBUG: No suitable description pattern found for {url}.")
        return html_content, None

    except Exception as e:
        print(f"Error fetching page content or extracting description for {url}: {e}")
        return None, None


def find_author_details_tool(author_id: str, api_key: str) -> dict:
    """ Retrieves detailed information for a specific Google Scholar author profile
        and scrapes article links directly from the author's profile page.

    Args:
        author_id: The unique ID of the author (e.g., "2EpSYrcAAAAJ").
        api_key: The SerpApi API key.

    Returns:
        A dictionary containing the author's details 
        (name, thumbnail, author profile url, affiliations, interests),
        a list of their articles (from SerpApi), and a list of scraped article links.
        Returns an empty dictionary if not found or an error occurs.
    """

    base_url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_scholar_author",  
        "author_id": author_id,
        "api_key": api_key,
        "as_sdt": "as_vis"
    }
    try:
        print(f"Calling SerpApi for author_id: {author_id}")
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status() 
        results = response.json()

        author_details = {}
        processed_articles = []
        scraped_article_urls = []

        if "author" in results:
            author_data = results["author"]
            author_details = {
                "name": author_data.get("name", "N/A"),
                "author image": author_data.get("thumbnail", "N/A")
                if author_data.get("thumbnail") != "https://scholar.google.com/citations/images/avatar_scholar_128.png"
                else "N/A", 
                "affiliations": author_data.get("affiliations", "N/A"),
                "interests": [
                    interest.get("title", "N/A")
                    for interest in author_data.get("interests", [])
                ]
            }
            
        author_profile_url = results["search_metadata"].get("google_scholar_author_url", "N/A")
        author_details["author profile url"] = author_profile_url
        print(f"DEBUG: Author profile URL retrieved: {author_profile_url}")
     
        if author_profile_url and author_profile_url != "N/A":
            scraped_article_urls = _scrape_article_links_from_profile(author_profile_url)
            print(f"DEBUG: Scraped {len(scraped_article_urls)} article links from profile.")
   

        if "articles" in results:
            for article in results["articles"][:5]: # Limiting to top 5 articles
                processed_articles.append({
                    "title": article.get("title", "N/A"),
                    "link": article.get("link", "N/A"),
                    "authors": article.get("authors", "N/A"),
                    "publication": article.get("publication", "N/A"),
                    "cited_by_value": article.get("cited_by", {}).get("value", "N/A"),
                    "year": article.get("year", "N/A")
                })
            print(f"DEBUG: Processed {len(processed_articles)} articles from SerpApi results.")

        return {
            "author": author_details,
            "articles": processed_articles,
            "scraped_article_links": scraped_article_urls
        }

    except requests.exceptions.Timeout:
        print(f"Error: Timeout occurred while fetching author details from SerpApi. The server took too long to respond.")
        return {"error": "SerpApi request timed out."}
    except requests.exceptions.RequestException as e:
        print(f"A request error occurred: {e}")
        return {"error": f"Request error: {e}"}
    except Exception as e:
        print(f"An unexpected non-requests error occurred: {e}")
        return {"error": f"Unexpected error: {e}"}


async def main():
    # Hardcoded SERPAPI_API_KEY as requested
    SERPAPI_API_KEY = "d6e2706ac32cc376b8727e406965dc5f7c9d95cba8bcd0a925801930d022c6f5" 
    
    test_author_id = "2EpSYrcAAAAJ" 
    print(f"Searching for author details and scraping article links for ID: {test_author_id}")

    try:
        await initialize_playwright_browser() 

        details = find_author_details_tool(test_author_id, SERPAPI_API_KEY) 

        if "error" in details:
            print(f"An error occurred: {details['error']}")
        else:
            print("\n--- Author Details ---")
            for key, value in details["author"].items():
                print(f"{key}: {value}")

            print("\n--- Articles (from SerpApi) ---")
            if details["articles"]:
                for i, article in enumerate(details["articles"]):
                    print(f"\nArticle {i+1}:")
                    for k, v in article.items():
                        print(f"  {k}: {v}")
                    
                    if article['link'] and article['link'] != 'N/A':
                        print(f"  Fetching HTML content and scraping description for SerpApi link: {article['link']}")
                        html_content, description = await _get_page_content_and_description(article['link']) 
                        if description:
                            print(f"  Description found in HTML: {description[:200]}...")
                        else:
                            print(f"  No description found in HTML for this SerpApi article link.")

                    else:
                        print(f"  Skipping HTML fetch: No valid link for this SerpApi article.")

            else:
                print("No articles found via SerpApi.")
            
            print("\n--- Scraped Article Links (from profile page) ---")
            if details["scraped_article_links"]:
                for i, link in enumerate(details["scraped_article_links"]):
                    print(f"\nLink {i+1}: {link}")
                    
                    print(f"  Fetching HTML content and scraping description for scraped article link: {link}")
                    html_content, description = await _get_page_content_and_description(link)
                    if description:
                        print(f"  Description found in HTML: {description[:200]}...") 
                    else:
                        print(f"  No description found in HTML for this scraped article link.")

            else:
                print("No additional article links scraped from the profile page. This is common if the author's profile doesn't directly link to viewable article pages or if there are scraping limitations.")

    except Exception as e:
        print(f"An unhandled error occurred in main: {e}")
    finally:
        await close_playwright_browser() 

if __name__ == "__main__":
    asyncio.run(main())