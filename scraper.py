import requests
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin
import random
import time
from typing import Dict, Tuple, Optional, List

BASE_URL = "https://www.cheese.com"

def absolute_url(url: Optional[str]) -> Optional[str]:
    """Convert relative URL to absolute URL."""
    if not url:
        return None
    return urljoin(BASE_URL, url)

def get_cheese_of_the_day() -> Tuple[str, str]:
    """
    Fetch the current Cheese of the Day.
    
    Returns:
        Tuple of (full_url, cheese_name)
    
    Raises:
        ValueError: If cheese of the day section cannot be found
        requests.RequestException: If request fails
    """
    try:
        resp = requests.get(BASE_URL, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        section = soup.find(string=lambda t: t and "Cheese of the day" in t)
        if not section:
            raise ValueError("Couldn't locate the 'Cheese of the day' section.")
        
        parent = section.find_parent()
        cheese_anchor = parent.find_next("a")
        if not cheese_anchor:
            raise ValueError("Couldn't find cheese link in the daily section.")
            
        name = cheese_anchor.get_text(strip=True)
        href = cheese_anchor.get("href")
        full_url = urljoin(BASE_URL, href)
        return full_url, name
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch cheese of the day: {e}")

def get_cheese_details(cheese_url: str) -> Dict[str, any]:
    """
    Extract detailed information about a specific cheese.
    
    Args:
        cheese_url: URL of the cheese page
        
    Returns:
        Dictionary containing cheese details
        
    Raises:
        requests.RequestException: If request fails
    """
    try:
        resp = requests.get(cheese_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        data = {}
        data['source_url'] = cheese_url

        # Extract cheese name
        h1 = soup.find('h1')
        if h1:
            data['name'] = h1.get_text(strip=True)
        elif soup.title:
            data['name'] = soup.title.string.strip()
        else:
            data['name'] = "Unknown Cheese"

        # Extract main image (prefer og:image for better quality)
        img_url = None
        og = soup.find('meta', property='og:image')
        if og and og.get('content'):
            img_url = og['content']
        else:
            # Fallback to thumbnail or first image
            thumb = soup.find("div", class_="thumb")
            if thumb and thumb.find('img'):
                img_tag = thumb.find('img')
                img_url = img_tag.get('src') or img_tag.get('data-src')
            else:
                img_tag = soup.find('img')
                if img_tag:
                    img_url = img_tag.get('src') or img_tag.get('data-src')
        
        data['image_url'] = absolute_url(img_url)

        # Extract structured fields
        field_mapping = {
            "Made from": "made_from",
            "Country of origin": "country_of_origin", 
            "Region": "region",
            "Family": "family",
            "Type": "type",
            "Texture": "texture",
            "Colour": "colour",
            "Flavor": "flavour",
            "Flavour": "flavour",  # Handle both spellings
            "Aroma": "aroma",
            "Vegetarian": "vegetarian"
        }
        
        for label, key in field_mapping.items():
            data[key] = None
            # Look for span or strong tags containing the field label
            span = soup.find(lambda tag: tag.name in ['span', 'strong', 'b'] and 
                           tag.get_text(strip=True).startswith(label))
            if span:
                # Try to find linked value first
                a = span.find_next('a')
                if a and a.get_text(strip=True):
                    data[key] = a.get_text(strip=True)
                else:
                    # Look for text in next sibling
                    ns = span.next_sibling
                    if isinstance(ns, NavigableString):
                        val = ns.strip().lstrip(':').strip()
                        if val:
                            data[key] = val
                    elif ns and hasattr(ns, 'get_text'):
                        text = ns.get_text(strip=True).lstrip(':').strip()
                        if text:
                            data[key] = text

        # Extract description/about section
        about_text = None
        about_images = []
        
        # Look for "What is [cheese name]" section
        about_h2 = None
        for tag in soup.find_all(['h2', 'h3']):
            text = tag.get_text().lower()
            if 'what is' in text or 'about' in text:
                about_h2 = tag
                break

        if about_h2:
            node = about_h2.find_next_sibling()
            paragraphs = []
            while node and (node.name not in ['h2', 'h3']):
                if hasattr(node, "find_all"):
                    # Collect images
                    for im in node.find_all('img'):
                        src = im.get('src') or im.get('data-src')
                        if src:
                            about_images.append(absolute_url(src))
                
                if node.name == 'p' and node.get_text(strip=True):
                    paragraphs.append(node.get_text(strip=True))
                node = node.find_next_sibling()
            
            about_text = " ".join(paragraphs).strip() if paragraphs else None

        # Fallback: look for description container
        if not about_text:
            containers = soup.find_all("div", class_=["wiki-content", "description", "content"])
            for container in containers:
                if container:
                    # Collect images
                    for im in container.find_all('img'):
                        src = im.get('src') or im.get('data-src')
                        if src:
                            about_images.append(absolute_url(src))
                    
                    # Get text from paragraphs
                    paragraphs = [p.get_text(strip=True) for p in container.find_all('p') if p.get_text(strip=True)]
                    if paragraphs:
                        about_text = " ".join(paragraphs)
                        break
                    else:
                        text = container.get_text(strip=True)
                        if text and len(text) > 20:  # Ensure it's substantial
                            about_text = text
                            break

        # Final fallback: first few paragraphs
        if not about_text:
            paragraphs = [p.get_text(strip=True) for p in soup.find_all('p')[:5] if p.get_text(strip=True)]
            about_text = " ".join(paragraphs) if paragraphs else None

        data['about'] = about_text or "No description available."

        # Clean up and deduplicate images
        about_images = list(dict.fromkeys([i for i in about_images if i]))
        if data['image_url'] and data['image_url'] not in about_images:
            about_images.insert(0, data['image_url'])
        data['about_images'] = about_images

        return data
        
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch cheese details from {cheese_url}: {e}")

def get_random_cheese(max_retries: int = 15) -> Dict[str, any]:
    """
    Fetch a random cheese from the alphabetical listing.
    
    Args:
        max_retries: Maximum number of attempts to find a cheese
        
    Returns:
        Dictionary containing random cheese details
        
    Raises:
        ValueError: If no cheese found after max retries
    """
    letters = list("abcdefghijklmnopqrstuvwxyz")
    attempted_letters = set()
    
    for attempt in range(max_retries):
        # Choose a random letter we haven't tried yet
        available_letters = [l for l in letters if l not in attempted_letters]
        if not available_letters:
            # Reset if we've tried all letters
            attempted_letters.clear()
            available_letters = letters
            
        random_letter = random.choice(available_letters)
        attempted_letters.add(random_letter)
        
        try:
            page_url = f"{BASE_URL}/alphabetical/{random_letter}/"
            resp = requests.get(page_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for cheese links in various possible selectors
            cheese_links = []
            selectors = [
                ".cheese-item a",
                ".cheese-list a", 
                "a[href*='/cheese/']",
                ".item a",
                "ul li a"
            ]
            
            for selector in selectors:
                links = [a.get("href") for a in soup.select(selector) if a.get("href")]
                if links:
                    cheese_links.extend(links)
                    break
            
            # Filter for actual cheese page links
            valid_links = [link for link in cheese_links if '/cheese/' in link or link.startswith('/')]
            
            if valid_links:
                selected = random.choice(valid_links)
                full_url = urljoin(BASE_URL, selected)
                return get_cheese_details(full_url)
                
            # Add small delay between attempts
            time.sleep(0.5)
            
        except requests.RequestException as e:
            print(f"Error fetching from letter {random_letter}: {e}")
            continue
        except Exception as e:
            print(f"Unexpected error with letter {random_letter}: {e}")
            continue

    raise ValueError(f"No cheeses found after {max_retries} random attempts.")

# Enhanced function for getting multiple random cheeses
def get_multiple_random_cheeses(count: int = 3) -> List[Dict[str, any]]:
    """
    Get multiple random cheeses (useful for variety).
    
    Args:
        count: Number of random cheeses to fetch
        
    Returns:
        List of cheese detail dictionaries
    """
    cheeses = []
    max_attempts = count * 3  # Allow more attempts than requested count
    
    for _ in range(max_attempts):
        if len(cheeses) >= count:
            break
            
        try:
            cheese = get_random_cheese()
            # Avoid duplicates
            if not any(c.get('name') == cheese.get('name') for c in cheeses):
                cheeses.append(cheese)
        except Exception as e:
            print(f"Error fetching random cheese: {e}")
            continue
    
    return cheeses

if __name__ == "__main__":
    print("Testing Cheese Scraper...")
    
    try:
        # Test daily cheese
        print("\n=== Testing Daily Cheese ===")
        url, name = get_cheese_of_the_day()
        print(f"Cheese of the day: {name}")
        print(f"URL: {url}")
        
        details = get_cheese_details(url)
        print(f"\nDetails for {details['name']}:")
        for key, value in details.items():
            if key != 'about_images':  # Skip image list for cleaner output
                print(f"  {key}: {value}")
        
        # Test random cheese
        print("\n=== Testing Random Cheese ===")
        random_cheese = get_random_cheese()
        print(f"\nRandom cheese: {random_cheese['name']}")
        print(f"Country: {random_cheese.get('country_of_origin', 'Unknown')}")
        print(f"Type: {random_cheese.get('type', 'Unknown')}")
        
    except Exception as e:
        print(f"Error during testing: {e}")