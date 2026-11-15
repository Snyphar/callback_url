import requests
from pathlib import Path

url = "https://email.gofcom.com/v1/emails/send"

mail_list = ["snyphar.ex@gmail.com","touhidulislamchowdhury.cse@gmail.com","uk20wholesale@gmail.com", 
             "runwaytravelsolution@gmail.com", "jiliton@yahoo.com", "jameshasan2026@outlook.com",
             "businesshelpdesk.uk@gmail.com", "rubel3210@outlook.com"]

template_path = Path(__file__).with_name("template.html")
html_content = template_path.read_text(encoding="utf-8")

for email in mail_list:
    payload = {
        "from": "hello@smsbusinesshelp.com",
        "to": email,
        "subject": "Hello from Python",
        "domainName": "smsbusinesshelp.com",
    "fromPrefix": "hello",
    "text": "Sent via Python requests",
    "html": html_content,
}
    headers = {
        "x-api-key": "LM_c8da014914b5b01e1e506279b01f5e5db95720c849108055",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    print(response.json())