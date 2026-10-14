import unittest

if __name__ != "__main__":
    raise unittest.SkipTest("Manual live-server API check; run as a script.")

import requests


data = {
    "algorithm": "RR"
}


response = requests.post(
    "http://127.0.0.1:5000/schedule",
    json=data
)


print(response.json())