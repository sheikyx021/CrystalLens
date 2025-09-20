from apify_client import ApifyClient
from flask import current_app
import time
import logging
from app.models import get_setting

logger = logging.getLogger(__name__)

class ApifyService:
    """Service for interacting with Apify API."""
    
    # Apify Actor IDs
    TWITTER_SCRAPER_ID = "61RPP7dywgiy0JPD0"
    FACEBOOK_SCRAPER_ID = "KoJrdxJCTtpon81KY"
    
    def __init__(self):
        """Initialize Apify client."""
        # Prefer DB setting, fallback to config/env
        api_token = get_setting('APIFY_API_TOKEN', current_app.config.get('APIFY_API_TOKEN'))
        if not api_token:
            raise ValueError("APIFY_API_TOKEN not configured")
        
        self.client = ApifyClient(api_token)
        # Read max posts from settings if available
        max_posts_setting = get_setting('MAX_POSTS_PER_SCRAPE', None)
        try:
            self.max_items = int(max_posts_setting) if max_posts_setting is not None else int(current_app.config.get('MAX_POSTS_PER_SCRAPE', 1000))
        except Exception:
            self.max_items = int(current_app.config.get('MAX_POSTS_PER_SCRAPE', 1000))
    
    def scrape_twitter_profile(self, username, max_items=None):
        """
        Scrape Twitter profile posts.
        
        Args:
            username (str): Twitter username (without @)
            max_items (int): Maximum number of posts to scrape
            
        Returns:
            dict: Run information with run_id and status
        """
        if max_items is None:
            max_items = self.max_items
        
        # Prepare Twitter scraper input
        run_input = {
            "twitterHandles": [username],
            "maxItems": max_items,
            "sort": "Latest",
            "tweetLanguage": "en",
            "includeSearchTerms": False,
            "onlyImage": False,
            "onlyQuote": False,
            "onlyTwitterBlue": False,
            "onlyVerifiedUsers": False
        }
        
        try:
            # Start the scraping job
            run = self.client.actor(self.TWITTER_SCRAPER_ID).call(run_input=run_input)
            
            logger.info(f"Started Twitter scraping for @{username}, run_id: {run['id']}")
            
            return {
                'run_id': run['id'],
                'status': 'running',
                'platform': 'twitter',
                'username': username
            }
            
        except Exception as e:
            logger.error(f"Error starting Twitter scraping for @{username}: {str(e)}")
            raise
    
    def scrape_facebook_page(self, page_url, max_items=None):
        """
        Scrape Facebook page posts.
        
        Args:
            page_url (str): Facebook page URL
            max_items (int): Maximum number of posts to scrape
            
        Returns:
            dict: Run information with run_id and status
        """
        if max_items is None:
            max_items = self.max_items
        # Enforce Facebook posts cap at 50 max as requested
        max_items = min(int(max_items), 50)
        
        # Prepare Facebook scraper input
        run_input = {
            "startUrls": [{"url": page_url}],
            "resultsLimit": max_items,
            "captionText": True,
            "commentsMode": "RANKED_UNFILTERED",
            "maxComments": 10,
            "maxCommentsDepth": 1,
            "maxReviews": 0,
            "maxPosts": max_items
        }
        
        try:
            # Start the scraping job
            run = self.client.actor(self.FACEBOOK_SCRAPER_ID).call(run_input=run_input)
            
            logger.info(f"Started Facebook scraping for {page_url}, run_id: {run['id']}")
            
            return {
                'run_id': run['id'],
                'status': 'running',
                'platform': 'facebook',
                'page_url': page_url
            }
            
        except Exception as e:
            logger.error(f"Error starting Facebook scraping for {page_url}: {str(e)}")
            raise
    
    def get_run_status(self, run_id):
        """
        Get the status of a scraping run.
        
        Args:
            run_id (str): Apify run ID
            
        Returns:
            dict: Run status information
        """
        try:
            run = self.client.run(run_id).get()
            
            return {
                'run_id': run_id,
                'status': run['status'],
                'started_at': run.get('startedAt'),
                'finished_at': run.get('finishedAt'),
                'stats': run.get('stats', {}),
                'error_message': run.get('errorMessage')
            }
            
        except Exception as e:
            logger.error(f"Error getting run status for {run_id}: {str(e)}")
            return {
                'run_id': run_id,
                'status': 'error',
                'error_message': str(e)
            }
    
    def get_run_results(self, run_id):
        """
        Get the results of a completed scraping run.
        
        Args:
            run_id (str): Apify run ID
            
        Returns:
            list: List of scraped posts/data
        """
        try:
            run = self.client.run(run_id).get()
            
            if run['status'] != 'SUCCEEDED':
                logger.warning(f"Run {run_id} not completed successfully: {run['status']}")
                return []
            
            # Get dataset ID
            dataset_id = run.get('defaultDatasetId')
            if not dataset_id:
                logger.error(f"No dataset found for run {run_id}")
                return []
            
            # Fetch results
            results = []
            for item in self.client.dataset(dataset_id).iterate_items():
                results.append(item)
            
            logger.info(f"Retrieved {len(results)} items from run {run_id}")
            return results
            
        except Exception as e:
            logger.error(f"Error getting run results for {run_id}: {str(e)}")
            return []
    
    def wait_for_completion(self, run_id, timeout=300, poll_interval=10):
        """
        Wait for a scraping run to complete.
        
        Args:
            run_id (str): Apify run ID
            timeout (int): Maximum time to wait in seconds
            poll_interval (int): Time between status checks in seconds
            
        Returns:
            dict: Final run status
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status_info = self.get_run_status(run_id)
            
            if status_info['status'] in ['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT']:
                return status_info
            
            time.sleep(poll_interval)
        
        # Timeout reached
        logger.warning(f"Run {run_id} timed out after {timeout} seconds")
        return {
            'run_id': run_id,
            'status': 'timeout',
            'error_message': f'Run timed out after {timeout} seconds'
        }
    
    def extract_post_content(self, raw_data, platform):
        """
        Extract relevant content from raw scraped data.
        
        Args:
            raw_data (list): Raw scraped data from Apify
            platform (str): Platform name (twitter/facebook)
            
        Returns:
            list: Processed posts with standardized format
        """
        processed_posts = []
        
        for item in raw_data:
            try:
                if platform == 'twitter':
                    post = self._process_twitter_post(item)
                elif platform == 'facebook':
                    post = self._process_facebook_post(item)
                else:
                    continue
                
                if post:
                    processed_posts.append(post)
                    
            except Exception as e:
                logger.error(f"Error processing {platform} post: {str(e)}")
                continue
        
        return processed_posts
    
    def _process_twitter_post(self, item):
        """Process a single Twitter post."""
        return {
            'platform': 'twitter',
            'post_id': item.get('id'),
            'text': item.get('text', ''),
            'author': item.get('author', {}).get('userName', ''),
            'created_at': item.get('createdAt'),
            'retweet_count': item.get('retweetCount', 0),
            'like_count': item.get('likeCount', 0),
            'reply_count': item.get('replyCount', 0),
            'is_retweet': item.get('isRetweet', False),
            'url': item.get('url', ''),
            'hashtags': item.get('hashtags', []),
            'mentions': item.get('mentions', []),
            'raw_data': item
        }
    
    def _process_facebook_post(self, item):
        """Process a single Facebook post."""
        return {
            'platform': 'facebook',
            'post_id': item.get('postId'),
            'text': item.get('text', ''),
            'author': item.get('authorName', ''),
            'created_at': item.get('time'),
            'like_count': item.get('likesCount', 0),
            'comment_count': item.get('commentsCount', 0),
            'share_count': item.get('sharesCount', 0),
            'post_type': item.get('postType', ''),
            'url': item.get('postUrl', ''),
            'images': item.get('images', []),
            'raw_data': item
        }
