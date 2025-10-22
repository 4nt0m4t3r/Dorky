# Dorky

Get vulnerable websites using google dorking

## Installation

``` 
git clone https://github.com/aNT8080/Dorky.git
cd Dorky
pip3 install -r requirements.txt 
```

## Usage


<img width="1174" height="408" alt="image" src="https://github.com/user-attachments/assets/5ee11f91-66df-4a2a-a260-c3fe51516db4" />


### With a proxy list:
```
 python3 dorky.py -qF dorks.txt   -o result.output --pages 100 --headful  -v


```

### Without a proxy list:
```
 python3 dorky.py -qF dorks/all_google_dorks.txt -o result.output

```
