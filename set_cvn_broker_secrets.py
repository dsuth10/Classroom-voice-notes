from getpass import getpass
import keyring

SERVICE_NAME = "ClassroomVoiceNotes"

print("Storing Classroom Voice Notes broker secrets in Windows Credential Manager.")
print("The values you type or paste will not be displayed.")

hmac_secret = getpass("Paste PRODUCTION CVN_HMAC_SECRET: ").strip()
bearer_token = getpass("Paste PRODUCTION CVN_BEARER_TOKEN: ").strip()

if len(hmac_secret) != 64:
    raise ValueError(f"CVN_HMAC_SECRET should be 64 hex characters, got {len(hmac_secret)}")

if len(bearer_token) != 64:
    raise ValueError(f"CVN_BEARER_TOKEN should be 64 hex characters, got {len(bearer_token)}")

keyring.set_password(SERVICE_NAME, "cvn_hmac_secret", hmac_secret)
keyring.set_password(SERVICE_NAME, "cvn_bearer_token", bearer_token)

print("Secrets stored successfully in Windows Credential Manager.")
print("Service:", SERVICE_NAME)
print("Stored keys: cvn_hmac_secret, cvn_bearer_token")