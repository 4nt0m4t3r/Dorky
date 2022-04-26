# Dorky

Get vulnerable website using google dorking

## Installation

``` 
git clone https://github.com/aNT8080/Dorky.git
cd Dorky
pip3 install -r requirements.txt 
```

## Usage


![Screenshot from 2022-04-25 17-11-51](https://user-images.githubusercontent.com/39093520/165118652-0c8be1e2-5fd4-4e77-8d8a-13dd6bc3e2dd.png)


### With a proxy list:
```
 python3 dorky.py -qF dorks/all_google_dorks.txt -o result.output -x proxies.txt


```

### Without a proxy list:
```
 python3 dorky.py -qF dorks/all_google_dorks.txt -o result.output

```
