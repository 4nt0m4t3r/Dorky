import requests, re
import argparse
from functools import partial
from multiprocessing import Pool
from bs4 import BeautifulSoup as bsoup
from termcolor import cprint
import random

def get_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('-x', '--proxy-file', dest='proxyfile', help='Specify the filename containing the list of proxies')
    parser.add_argument('-qF', '--queries-file', dest='queriesfile', help='Specify the filename containing the list of queries')
    parser.add_argument('-P', '--processes', dest='processes', help='Specify the Number of Processes (Default: 2)')    
    parser.add_argument('-o', '--output', dest='output', help='Output targets to a file')    
    options = parser.parse_args()
    return options


def google_search(query, proxies, page):
    x= random.randint(1, 499)
    
    result = []
    base_url = 'https://www.google.com/search'
    params   = { 'q': query, 'start': page * 10 }
    if proxies:
        proxy="http://"+proxies[x]
        proxies = {
        "http": "http://"+proxies[x],
        "https": "http://"+proxies[x],
        }
    headers_list = [
            { 
            'authority': 'httpbin.org', 
            'cache-control': 'max-age=0', 
            'sec-ch-ua': '"Chromium";v="92", " Not A;Brand";v="99", "Google Chrome";v="92"', 
            'sec-ch-ua-mobile': '?0', 
            'upgrade-insecure-requests': '1', 
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36', 
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9', 
            'sec-fetch-site': 'none', 
            'sec-fetch-mode': 'navigate', 
            'sec-fetch-user': '?1', 
            'sec-fetch-dest': 'document', 
            'accept-language': 'en-US,en;q=0.9', 
            } , 
            { 
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8", 
            "Accept-Encoding": "gzip, deflate, br", 
            "Accept-Language": "en-US,en;q=0.5", 
            "Host": "httpbin.org", 
            "Sec-Fetch-Dest": "document", 
            "Sec-Fetch-Mode": "navigate", 
            "Sec-Fetch-Site": "none", 
            "Sec-Fetch-User": "?1", 
            "Upgrade-Insecure-Requests": "1", 
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:90.0) Gecko/20100101 Firefox/90.0", 
            "X-Amzn-Trace-Id": "Root=1-60ff12e8-229efca73430280304023fb9" 
            } , 
            { 
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", 
            "Accept-Encoding": "gzip, deflate, br", 
            "Accept-Language": "en-US,en;q=0.9", 
            "Host": "httpbin.org", 
            "Sec-Ch-Ua": "\"Chromium\";v=\"92\", \" Not A;Brand\";v=\"99\", \"Google Chrome\";v=\"92\"", 
            "Sec-Ch-Ua-Mobile": "?0", 
            "Sec-Fetch-Dest": "document", 
            "Sec-Fetch-Mode": "navigate", 
            "Sec-Fetch-Site": "none", 
            "Sec-Fetch-User": "?1", 
            "Upgrade-Insecure-Requests": "1", 
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36", 
            "X-Amzn-Trace-Id": "Root=1-60ff12bb-55defac340ac48081d670f9d" 
            } 
    ] 
    headers = random.choice(headers_list) 

    if proxies:
        resp = requests.get(base_url, params=params, headers=headers,proxies=proxies)
    else:
        resp = requests.get(base_url, params=params, headers=headers)
    soup = bsoup(resp.text, 'html.parser')
    links  = soup.findAll('cite')

    if "Our systems have detected unusual traffic from your computer network."  in resp.text or "Your client does not have permission to get URL"  in resp.text:
        ip=re.search("IP address: .*<br>",resp.text)
        cprint("BLOCKED ",'blue')
        cprint(ip,"blue")

    for link in links:
        result.append(link.text)
    return result


def search_result(q, pages, processes, result):
    counter = 0
    for range in result:
        for r in range:
            if counter==0:
                print()
                print(f'{q}')
                print('-' * 70)
                print()
            cprint('[+] ' + r,'red')
            counter += 1


options = get_arguments()

banner = '''

'########:::'#######::'########::'##:::'##:'##:::'##:
 ##.... ##:'##.... ##: ##.... ##: ##::'##::. ##:'##::
 ##:::: ##: ##:::: ##: ##:::: ##: ##:'##::::. ####:::
 ##:::: ##: ##:::: ##: ########:: #####::::::. ##::::
 ##:::: ##: ##:::: ##: ##.. ##::: ##. ##:::::: ##::::
 ##:::: ##: ##:::: ##: ##::. ##:: ##:. ##::::: ##::::
 ########::. #######:: ##:::. ##: ##::. ##:::: ##::::
........::::.......:::..:::::..::..::::..:::::..:::::

'''

def main():
    print()
    query_file = options.queriesfile
    pages = 2
    proxies=[]

    if  options.proxyfile:
        proxy_list = open(options.proxyfile)
        proxies = proxy_list.readlines()
    if not options.processes:
        processes = 2
    else:
        processes = options.processes
    final_result=[]
    with Pool(int(processes)) as p:
        with open(query_file,"r") as f:
            lines = f.readlines()
        for line in lines:
            query=line.strip()
            target = partial(google_search, query,proxies)
            result = p.map(target, range(int(pages)))
            final_result.append(result)
            search_result(query, pages, processes, result)

try:
    cprint(banner,'green')
    main()
except KeyboardInterrupt:
    print('\nGoodbye!')
    exit()
except TimeoutError:
    print('\n[-] You mau have been blocked by google.Please try again later....')
    pass
