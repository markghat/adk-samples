import os
import requests
from bs4 import BeautifulSoup
import re
import asyncio
from playwright.async_api import async_playwright

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

# (Keep _scrape_article_links_from_profile as is)
def _scrape_article_links_from_profile(profile_url: str) -> list[str]:
    """
    Scrapes an author's Google Scholar profile page to find direct article links.

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
    Fetches the HTML content of a page using Playwright and attempts to extract
    the article description.

    Args:
        url (str): The URL of the webpage.

    Returns:
        tuple[str | None, str | None]: A tuple containing the HTML content and the extracted description,
                                        or (None, None) if an error occurred.
    """
    html_content = None
    description_text = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Navigate to the URL and wait for network activity to settle
            await page.goto(url, wait_until='networkidle') 
            
            html_content = await page.content() # Get the rendered HTML content
            
            await browser.close()

            # Now, parse the HTML content to find the description
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # --- Attempt 1: Specific ID often used for description ---
            description_div = soup.find('div', id='gsc_vcd_descr')
            if description_div:
                description_text = description_div.get_text(separator=' ', strip=True)
                print(f"DEBUG: Found description using id='gsc_vcd_descr'")
                return html_content, description_text

            # --- Attempt 2: Blockquote elements (often used for abstracts/quotes) ---
            blockquote_tags = soup.find_all('blockquote')
            for bq in blockquote_tags:
                # Check if the blockquote seems like an abstract (e.g., not too short, part of main content)
                text = bq.get_text(separator=' ', strip=True)
                if len(text) > 50: # Arbitrary length check to filter out small quotes
                    description_text = text
                    print(f"DEBUG: Found description using blockquote tag.")
                    return html_content, description_text

            # --- Attempt 3: Divs with common 'abstract' or 'description' related classes/attributes ---
            # This is more general and might require inspection of common Google Scholar article pages
            # Add more selectors here if you inspect a page and find other common patterns.
            possible_description_divs = soup.find_all('div', class_=re.compile(r'abstract|description|snippet|gsc_vcd_content', re.IGNORECASE))
            for div in possible_description_divs:
                text = div.get_text(separator=' ', strip=True)
                if len(text) > 50: # Again, a length check
                    description_text = text
                    print(f"DEBUG: Found description using a common class name.")
                    return html_content, description_text
            
            # --- Attempt 4: Look for meta description tag (less common for full abstracts but worth a try) ---
            meta_description = soup.find('meta', attrs={'name': 'description'})
            if meta_description and meta_description.get('content'):
                description_text = meta_description.get('content').strip()
                if len(description_text) > 50:
                    print(f"DEBUG: Found description using meta description tag.")
                    return html_content, description_text

            # --- Fallback: Consider elements that contain a significant amount of text after the title/authors ---
            # This is a last resort and can be less accurate.
            # We might look for a <div class="gsc_vcd_field"> that contains "Description" or "Abstract"
            # Or just a large paragraph. This requires very specific inspection.
            
            print(f"DEBUG: No common description patterns found for {url}.")
            return html_content, None # No description found

    except Exception as e:
        print(f"Error fetching page content or extracting description for {url}: {e}")
        return None, None


# (Keep _download_page_as_pdf_playwright, find_author_details_tool, main as is)

async def _download_page_as_pdf_playwright(url: str, output_dir: str = "downloads") -> str | None:
    """
    Downloads a webpage as a PDF using Playwright (headless browser).
    This function generates the PDF directly from the rendered page.

    Args:
        url (str): The URL of the webpage to download.
        output_dir (str): The directory where the PDF should be saved.

    Returns:
        str | None: The path to the downloaded PDF file, or None if an error occurred.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Sanitize URL to create a filename
    filename_safe_url = re.sub(r'[^a-zA-Z0-9]', '_', url)
    # Limit filename length and add .pdf extension
    filename = f"{filename_safe_url[:100]}.pdf" 
    filepath = os.path.join(output_dir, filename)

    try:
        print(f"Attempting to download page {url} as PDF to {filepath} using Playwright...")
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Navigate to the URL and wait for network activity to settle
            await page.goto(url, wait_until='networkidle') 
            
            # Generate PDF
            await page.pdf(path=filepath, format='A4')
            
            await browser.close()
        
        print(f"Successfully downloaded page as PDF to: {filepath}")
        return filepath
    except Exception as e:
        print(f"Error converting page {url} to PDF with Playwright: {e}")
        return None


def find_author_details_tool(author_id: str) -> dict:
    """ Retrieves detailed information for a specific Google Scholar author profile
        and scrapes article links directly from the author's profile page.

    Args:
        author_id: The unique ID of the author (e.g., "2EpSYrcAAAAJ").

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
        "api_key": SERPAPI_API_KEY,
        "as_sdt": "as_vis"
    }
    try:
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
        print(f"DEBUG: Author profile URL: {author_profile_url}")
     
        if author_profile_url and author_profile_url != "N/A":
            scraped_article_urls = _scrape_article_links_from_profile(author_profile_url)
   

        if "articles" in results:
            for article in results["articles"][:5]:
                processed_articles.append({
                    "title": article.get("title", "N/A"),
                    "link": article.get("link", "N/A"),
                    "authors": article.get("authors", "N/A"),
                    "publication": article.get("publication", "N/A"),
                    "cited_by_value": article.get("cited_by", {}).get("value", "N/A"),
                    "year": article.get("year", "N/A")
                })

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
    if not SERPAPI_API_KEY:
        print("SERPAPI_API_KEY environment variable not set. Please set it to run the example.")
    else:
        test_author_id = "2EpSYrcAAAAJ" 
        print(f"Searching for author details and scraping article links for ID: {test_author_id}")
        details = find_author_details_tool(test_author_id)

        if "error" in details:
            print(f"An error occurred: {details['error']}")
        else:
            print("\n--- Author Details ---")
            for key, value in details["author"].items():
                print(f"{key}: {value}")

            print("\n--- Articles (from SerpApi) ---")
            if details["articles"]:
                for i, article in enumerate(details["articles"]):
                    print(f"Article {i+1}:")
                    for k, v in article.items():
                        print(f"  {k}: {v}")
                    
                    print(f"  Fetching content and scraping description for SerpApi link: {article['link']}")
                    html_content, description = await _get_page_content_and_description(article['link'])
                    if description:
                        print(f"  Description found: {description[:200]}...") # Print first 200 chars
                    else:
                        print(f"  No description found for this SerpApi article link.")

                    downloaded_path = await _download_page_as_pdf_playwright(article['link'])
                    if downloaded_path:
                        print(f"  Page PDF downloaded to: {downloaded_path}")
                    else:
                        print(f"  Could not download page as PDF for this SerpApi article link.")
            else:
                print("No articles found via SerpApi.")
            
            print("\n--- Scraped Article Links (from profile page) ---")
            if details["scraped_article_links"]:
                for i, link in enumerate(details["scraped_article_links"]):
                    print(f"Link {i+1}: {link}")
                    
                    print(f"  Fetching content and scraping description for scraped article link: {link}")
                    html_content, description = await _get_page_content_and_description(link)
                    if description:
                        print(f"  Description found: {description[:200]}...") # Print first 200 chars
                    else:
                        print(f"  No description found for this scraped article link.")

                    downloaded_path = await _download_page_as_pdf_playwright(link)
                    if downloaded_path:
                        print(f"  Page PDF downloaded to: {downloaded_path}")
                    else:
                        print(f"  Could not download page as PDF for this scraped article link.")
            else:
                print("No additional article links scraped from the profile page. This is common if the author's profile doesn't directly link to viewable article pages or if there are scraping limitations.")

if __name__ == "__main__":
    asyncio.run(main())