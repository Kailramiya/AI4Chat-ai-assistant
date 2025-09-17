import os
import json
import requests
from bs4 import BeautifulSoup
import asyncio
from playwright.async_api import async_playwright
from urllib.parse import urljoin, urlparse
import re

class WebsiteScraper:
    def __init__(self, base_url, max_pages=50):
        self.base_url = base_url
        self.max_pages = max_pages
        self.visited_urls = set()
        self.scraped_data = []
        
    def clean_text(self, text):
        # Remove extra whitespace and normalize
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n+', '\n', text)
        return text.strip()
    
    def extract_product_info(self, soup, url):
        # Try to extract structured product data
        product_data = {}
        
        # Look for JSON-LD structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Product':
                    product_data['name'] = data.get('name', '')
                    product_data['price'] = data.get('offers', {}).get('price', '')
                    product_data['description'] = data.get('description', '')
                    product_data['brand'] = data.get('brand', {}).get('name', '')
            except:
                continue
                
        # Extract price from common selectors
        price_selectors = ['.price', '.cost', '[class*="price"]', '[id*="price"]']
        for selector in price_selectors:
            price_elem = soup.select_one(selector)
            if price_elem and not product_data.get('price'):
                product_data['price'] = price_elem.get_text().strip()
                
        return product_data
    
    async def scrape_page_dynamic(self, url):
        """Scrape JavaScript-heavy pages with Playwright"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await page.wait_for_timeout(2000)  # Wait for dynamic content
                
                # Get page title
                title = await page.title()
                
                # Extract main content (avoid navigation, footer, etc.)
                content = await page.evaluate('''
                    () => {
                        // Remove script, style, nav, footer elements
                        const elementsToRemove = document.querySelectorAll('script, style, nav, footer, header, .navigation, .menu');
                        elementsToRemove.forEach(el => el.remove());
                        
                        // Get main content area
                        const mainContent = document.querySelector('main, .main, .content, .container') || document.body;
                        return mainContent.innerText;
                    }
                ''')
                
                await browser.close()
                return title, self.clean_text(content)
                
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                await browser.close()
                return None, None
    
    def scrape_page_static(self, url):
        """Scrape static pages with requests + BeautifulSoup"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                element.decompose()
            
            # Get title
            title = soup.title.string if soup.title else url
            
            # Extract main content
            main_content = soup.find('main') or soup.find(class_='main') or soup.find(class_='content') or soup.body
            text = main_content.get_text(separator='\n', strip=True) if main_content else ''
            
            # Extract product information
            product_info = self.extract_product_info(soup, url)
            
            return title, self.clean_text(text), product_info
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None, None, {}
    
    def get_page_links(self, soup, current_url):
        """Extract all internal links from a page"""
        links = set()
        domain = urlparse(self.base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(current_url, href)
            
            # Only include same-domain links
            if urlparse(full_url).netloc == domain:
                # Clean URL (remove fragments, etc.)
                clean_url = full_url.split('#')[0].split('?')[0]
                links.add(clean_url)
                
        return links
    
    async def scrape_website(self):
        """Main scraping function"""
        print(f"Starting to scrape {self.base_url}")
        
        # Start with the homepage
        urls_to_visit = [self.base_url]
        
        while urls_to_visit and len(self.scraped_data) < self.max_pages:
            current_url = urls_to_visit.pop(0)
            
            if current_url in self.visited_urls:
                continue
                
            self.visited_urls.add(current_url)
            print(f"Scraping: {current_url}")
            
            # Try static scraping first (faster)
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                response = requests.get(current_url, headers=headers, timeout=10)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Get more links to crawl
                new_links = self.get_page_links(soup, current_url)
                urls_to_visit.extend([link for link in new_links if link not in self.visited_urls])
                
                title, text, product_info = self.scrape_page_static(current_url)
                
            except:
                # Fallback to dynamic scraping
                title, text = await self.scrape_page_dynamic(current_url)
                product_info = {}
            
            if title and text:
                page_data = {
                    'url': current_url,
                    'title': title,
                    'content': text,
                    'product_info': product_info,
                    'page_type': self.classify_page(current_url, title, text)
                }
                self.scraped_data.append(page_data)
                print(f"Scraped: {title}")
        
        return self.scraped_data
    
    def classify_page(self, url, title, content):
        """Classify what type of page this is"""
        url_lower = url.lower()
        title_lower = title.lower()
        content_lower = content.lower()
        
        if '/product' in url_lower or 'product' in title_lower:
            return 'product'
        elif any(word in url_lower for word in ['/about', '/contact', '/faq', '/help']):
            return 'info'
        elif any(word in content_lower for word in ['shipping', 'delivery', 'return', 'policy']):
            return 'policy'
        else:
            return 'general'
    
    def save_data(self, filename='scraped_data.json'):
        """Save scraped data to JSON file"""
        os.makedirs('data', exist_ok=True)
        with open(f'data/{filename}', 'w', encoding='utf-8') as f:
            json.dump(self.scraped_data, f, ensure_ascii=False, indent=2)
        
        print(f"Saved {len(self.scraped_data)} pages to data/{filename}")

# Usage
if __name__ == "__main__":
    # Replace with the website you want to scrape
    website_url = "https://b2b-demo-store.myshopify.com"  # CHANGE THIS
    
    scraper = WebsiteScraper(website_url, max_pages=100)
    scraped_data = asyncio.run(scraper.scrape_website())
    scraper.save_data()
