from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument("--window-size=1200,900")
options.add_argument("--window-position=100,100")

driver = webdriver.Chrome(options=options)
driver.get("http://localhost:8765/form.html")
print(f"Browser running with title: {driver.title}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
