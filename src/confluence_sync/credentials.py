import getpass
import keyring


_SERVICE_NAME = "confluence-sync"
_EMAIL_ACCOUNT = "email"
_TOKEN_ACCOUNT = "api-token"


def store_credentials(email: str, api_token: str) -> None:
    if not email.strip() or not api_token:
        raise ValueError("email and API token are required")
    keyring.set_password(_SERVICE_NAME, _EMAIL_ACCOUNT, email.strip())
    keyring.set_password(_SERVICE_NAME, _TOKEN_ACCOUNT, api_token)


def load_credentials() -> tuple[str, str]:
    email = keyring.get_password(_SERVICE_NAME, _EMAIL_ACCOUNT)
    api_token = keyring.get_password(_SERVICE_NAME, _TOKEN_ACCOUNT)
    if not email or not api_token:
        raise ValueError("credentials are missing; run 'confluence-sync credentials set'")
    return email, api_token


def prompt_and_store_credentials() -> None:
    email = input("Atlassian account email: ").strip()
    api_token = getpass.getpass("Atlassian API token: ")
    store_credentials(email, api_token)