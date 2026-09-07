from video_performance import video_performance

# Accented names are the auth keys (auth.py); video_performance normalizes
# them to plain ASCII before writing to BigQuery.
brands = [
    "Eileen Grace",
    "Mamaway",
    "SHRD",
    "Miss Daisy",
    "Polynia",
    "CHESS",
    "Cléviant",
    "Mossèru",
    "Evoke",
    "Dr Jou",
    "Mirae",
    "Swissvita",
    "G-Belle",
    "Past Nine",
    "Nutri & Beyond",
    "Ivy & Lily",
    "Naruko",
    "Relove",
    "Joey & Roo",
    "Rocketindo Shop",
    "M2",
]

# Plan for deployment:
# 1. Change startDate to D-7 and endDate to D-1
# 2. Test on local all brands. 
# 3. Deploy to Cloud Run job
# 4. Test on Cloud Run with manual trigger. 
# 5. Test on Cloud Run with time trigger

def main():
    for brand in brands:
        print("Brand: ", brand)
        video_performance(brand)

main()