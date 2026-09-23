import requests
from api_susar.api_utilities import PATH_APPLICATION_CONFIGURATION_ENDPOINT, API_FICHA, ENV, MOCK_FICHA

def check_perm(access_token, perm_key):
    if MOCK_FICHA:
        return True
    response = requests.get(
                    f"{API_FICHA}{PATH_APPLICATION_CONFIGURATION_ENDPOINT}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    verify= True if ENV != "LOCALHOST" else False
                )
    if response.json().get("auth").get("grantedPolicies").get(perm_key):
        return True
    else:
        return False