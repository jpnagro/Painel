from os import getenv
from dopplersdk import DopplerSDK
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(raise_error_if_not_found=False))

# doppler = DopplerSDK()
# doppler.set_access_token(getenv('DOPPLER_TOKEN'))

# def config_environments():
#     project_id = getenv('DOPPLER_PROJECT')
#     config_name = getenv('DOPPLER_CONFIG')

#     variables_response = doppler.secrets.list(project=project_id, config=config_name)
#     variables = variables_response.secrets
#     vars_set = {}
#     for var_name, var_data in variables.items():
#         computed_value = var_data.get('computed')
#         if computed_value is not None:
#             vars_set[var_name] = computed_value

#     return vars_set

# env_vars = config_environments()

DATABASE_URL = getenv("DATABASE_URL")

ACCESS_TOKEN = getenv("ACCESS_TOKEN_CRM")
URL_CRM = getenv("URL_CRM")
BASE_URL_CRM = getenv("BASE_URL_CRM")
PIPELINE_ID = getenv("PIPELINE_ID")

DBNAME_MG = getenv("DBNAME_MG")
URI_MG = getenv("URI_MG")
COL_MG_C = getenv("COL_MG_C")

AUTH_KEY = getenv("AUTH_KEY")

OPENAI_API_KEY = getenv("OPENAI_API_KEY")