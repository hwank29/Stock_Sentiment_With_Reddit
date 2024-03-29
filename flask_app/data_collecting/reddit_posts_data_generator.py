# when called as scheduled task, relative import returns error 
try:
    from data_collecting.analyze_reddit_data import analyze_stock
except:
    pass
from dateutil.relativedelta import relativedelta
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from pathlib import Path
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime as dt, timezone
import praw
import nltk
import string
import csv
import re
import os 
import csv

nltk.download('punkt')
nltk.download('stopwords')

# imports mongo_ip used with celery 
# Mongo_ip = os.environ.get('MONGO_IP')

dotenv_path = Path('.env')
load_dotenv(dotenv_path=dotenv_path)

# imports mongo_uri
Mongo_URI = os.environ.get('MONGO_URI')
# connects to my mongodb uri when using celery 
# client = MongoClient(f'mongodb://{Mongo_ip}:27017/')
# connects to my cloud_based mongodb
client = MongoClient(Mongo_URI, server_api=ServerApi('1'))
# sets 'db' to posts_database 
db = client.posts_database
post_collection = db.post_collection
post_rank_collection = db.post_rank_collection

# praw set up
reddit = praw.Reddit(
    client_id=os.environ.get('my_client_id'),
    client_secret=os.environ.get('my_client_secret'),
    user_agent="my user agent",
)

# Organize company name and ticker dictionaries 
with open('data/S&P500_tickers_names.csv', 'r') as csv_file:
    csv_reader = csv.DictReader(csv_file)
    ticker_name_dict = {}
    company_name_dict = {}
    company_capitalize_dict = {}
    company_ticker_dict = {}
    for company in csv_reader:
        ticker_name_dict[company['Ticker'].lower()] = 0
        company_name_dict[company['Name'].lower()] = 0 
        company_capitalize_dict[company['Name'].lower()] = company['Name']
        company_ticker_dict[company['Name'].lower()]= company['Ticker'].lower() 

# Data cleaning unneccessary parts of selftext 
def cleaning(text):    
    text = text.lower()
    # Removes http and www website url
    text = re.sub('^https?://', "", text)
    # Removes special characters
    text = re.sub('<.*?>+', "", text)
    # Removes digits
    text = re.sub("\d+", "", text)
    # Removes tap and white space
    text = re.sub("\s\s+", " ", text)
    # Removes punctuation besides $ for ticker 
    text = text.translate(str.maketrans('', '', string.punctuation.replace('$','') + '’'))
    text_tokenize = word_tokenize(text)
    # Make a list variable for words that are not actually mentioned as tickers but give misinformation 
    new_stop_words = ['low', 'dow', 'see', 'k', 'amp', 'well', 'im', 'tech', 'key', 'peak', 'fast', 'hes', 'dd', 'factset', 'cost', 'share', 'shares', 'per', 'dont', 'any', 'one', '']
    # Makes a variable for stop words and remove any stop words from column title and selftext
    stop_words = stopwords.words('english')
    stop_words.extend(new_stop_words)
    text = " ".join([t for t in text_tokenize if not t in stop_words])
    return text

# counts stocks/tickers mentioned in each post
def name_counter(selftext):
    ticker_dict_copy = ticker_name_dict.copy()
    company_dict_copy = company_name_dict.copy()
    company_ticker_dict_copy = company_ticker_dict.copy()
    # Count ticker or company names mentioned in each post(a post can mention the same company name multple times, so one count per post)
    for word in word_tokenize(selftext):
        if word in list(ticker_dict_copy.keys()):
            ticker_dict_copy[word] += 1
        elif word in list(company_dict_copy.keys()):
            company_dict_copy[word] += 1
    # sums up the number of times a company is mentioned by name and ticker
    company_mentioned_together = company_dict_copy.copy()
    for key, value in company_ticker_dict_copy.items():
        company_mentioned_together[key] += ticker_name_dict[value]
    company_mentioned_together = {key: value for key, value in sorted(company_mentioned_together.items(), key=lambda item: item[1], reverse=True)}    
    
    name_list, mentioned_num = [], []
    for key, value in company_mentioned_together.items():
        name_list.append(key)
        mentioned_num.append(value)
    return [name_list, mentioned_num]

# Import negative, positive word files and convert it to a list 
neg_word_list = open('data/sentiment_wordslist/negative_words.txt', 'r').read().splitlines()
pos_word_list = open('data/sentiment_wordslist/positive_words.txt', 'r').read().splitlines()

# make variables to count negative, positive terms mentioned in selftext
neg_word_count, pos_word_count = 0, 0
# Count negative, positive words used and return the result and ratio
def sentiment_measure(title, selftext):
    """Code to find out which positive and negative words are most repeated"""
    # global neg_word_count, pos_word_count
    # for title in post_data['title']:
    #     for title_word in title.split():
    #         if title_word in neg_word_list:
    #             neg_word_count.append(title_word)
    #         elif title_word in pos_word_list:
    #             pos_word_count.append(title_word)
    # for text in post_data['selftext']:
    #     for text_word in text.split():
    #         if text_word in neg_word_list:
    #             neg_word_count.append(text_word)
    #         elif text_word in pos_word_list:
    #             pos_word_count.append(text_word)
    # counter_neg = Counter(neg_word_count)
    # counter_pos = Counter(pos_word_count)
    # print(counter_neg)
    # print(counter_pos)
    # counts how many times negative and positive words are mentioned in the gathered title and selftext
    neg_word_count, pos_word_count = 0, 0
    for title_word in title.split():
        if title_word in neg_word_list:
            neg_word_count += 1
        elif title_word in pos_word_list:
            pos_word_count += 1
    for text_word in selftext.split():
        if text_word in neg_word_list:
            neg_word_count += 1
        elif text_word in pos_word_list:
            pos_word_count += 1
    return [pos_word_count, neg_word_count]

# if first time using, get data within two years
two_years_from_today_epoch = int(dt.timestamp(dt.now(timezone.utc) - relativedelta(years=2)))
today_epoch = int(dt.timestamp(dt.now(timezone.utc)))
# function to generate data of posts in 'stocks' subreddit and input the post data into post_collection(mongodb)
def post_data_generator():
    """if first time using"""
    # start_time_input = two_years_from_today_epoch
    # end_time_input = today_epoch 
    # start_time_input = start_time
    latest_doc_time = 0
    # Pushshift ver
    # can pull 1000 reddit posts per request at max so loop to get every post
    # if first time (developer), needs to put 3 years of reddit post data into mongodb database; may take some time ;; better for regular usage to the user 
    # post_data_generator_uri = f'https://api.pushshift.io/reddit/search/submission?subreddit=stocks&after={start_time_input}&before={end_time_input}&size=1000&is_video=false&fields=id,created_utc,utc_datetime_str,title,score,selftext'
    # def get(uri):
    #     response = urlopen(uri, timeout=10)
    #     return json.loads(response.read())
    # posts = get(post_data_generator_uri)

    # praw ver 
    for post in reddit.subreddit("stocks").new(limit=None):
        if post_collection.count_documents({'created_utc': post.created_utc}, limit=1) == 0:
            # if selftext exists and no repeated document in collection
            if post.selftext != "[removed]" and post.selftext != '[deleted]' and post.selftext and post.upvote_ratio > 0.4 and post.score != 0:
                post_selftext = cleaning(post.selftext)
                post_title = cleaning(post.title)
                name_count = name_counter(post_selftext)
                post_document = {
                            'created_utc' : post.created_utc, 
                            'stocks_mentioned': name_count[0],
                            'mentioned_num': name_count[1],
                            'sentiment': sentiment_measure(post_title, post_selftext)}
                post_collection.update_one({"created_utc": post_document['created_utc']}, {"$set": post_document}, upsert=True)
            if (post.link_flair_text == "Company Analysis" or post.link_flair_text == "Company Discussion" 
                or post.link_flair_text == "Industry Discussion") and post.selftext != "[removed]" and post.selftext != '[deleted]' and post.score > 100:

                post_doc_rank = {
                            'link_flair_text': post.link_flair_text,
                            'score': post.score,
                            'created_utc' : post.created_utc, 
                            'url': post.url,
                            'title': post.title
                }
                post_rank_collection.update_one({"created_utc": post_doc_rank['created_utc']}, {"$set": post_document}, upsert=True)
        # delete old documents(older than two years) for data storage efficiency
        else:
            if post_collection.find({"created_utc": { "$lte" : two_years_from_today_epoch} }):
                pass
                post_collection.delete_many({"created_utc" : { "$lte" : two_years_from_today_epoch} })
                post_rank_collection.delete_many({"created_utc" : { "$lte" : two_years_from_today_epoch}})
            return
        
def post_data_analyzer(start_time, end_time):
    # Find reddit post data within the range of data inputted and return cursor    
    post_cur = post_collection.find({"created_utc": {"$gte": start_time, "$lte": end_time}}, {"_id" : 0, "created_utc" : 0})
    pos_count, neg_count = 0, 0    
    company_count = company_name_dict.copy()
    test = 0
    
    # loop through cursor 
    for field in post_cur:
        pos_count += field['sentiment'][0]
        neg_count += field['sentiment'][1]
        index = 0
        test += 1
        # when no more mentioned, move to next document
        for num in field['mentioned_num']:
            if num != 0:
                company_count[field['stocks_mentioned'][index]] += num
                index += 1
            else:
                break
    # sentiment ratio created and count company names mentioned
    sentiment_ratio = round(pos_count/neg_count, 5)
    company_count = sorted(company_count.items(), key=lambda x: x[1], reverse=True)[:25]
    data_mentioned_stock = {
        'Name' : [company_capitalize_dict[val[0]] for val in company_count],
        'Ticker' : [company_ticker_dict[val[0]].upper() for val in company_count],
        'Mentioned' : [dict[1] for dict in company_count],
        'Highest' : [],
        'Lowest' : [],
        'Change vs Dow': [],
        'Change vs S&P500': [],
        'Change vs Nasdaq': []
    } 
    post_df = analyze_stock(data_mentioned_stock, start_time, end_time)
    return [post_df[0], sentiment_ratio, pos_count, neg_count, post_df[1]]

# runs only when scheduler task is called
if __name__ == '__main__':
    post_data_generator()