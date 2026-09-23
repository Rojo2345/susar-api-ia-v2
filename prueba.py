import requests

url = "http://localhost:5002/susar"

with open(r"D:\Trabajo\archivo.pdf", "rb") as f:
    response = requests.post(
        url,
        files={"file": f},
        data={"provider": "openai"}
    )

print(response.status_code)
print(response.json())