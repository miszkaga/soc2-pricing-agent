from google_auth_oauthlib.flow import InstalledAppFlow
import os

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def generate_token():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    creds = flow.run_local_server(port=8080)

    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    print("Sukces! Plik token.json został utworzony.")

if __name__ == '__main__':
    generate_token()