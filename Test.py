import google.generativeai as genai
genai.configure(api_key="AIzaSyBOITJPK7wMJ66P8ur1AlMPKjh5K96F_XY")

models = genai.list_models()

for m in models:
    print(f"{m.name} - {m.supported_generation_methods}")
