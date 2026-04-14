Get supabase credentials from the api section in the project.
stream_listener will permanently listen to the data coming from the supabase database and constantly keep printing it/sending it to the risk agent as far as the risk agent is waiting for new data. 
test_insert was to test inserting function to check if the listener works 
simulate_stream simulates insertion every x seconds like data stream coming in real time taking the data from a csv file. Can be easily modified to take in data everytime a new data is gotten from an api so basically from data_gen too.
data_gen is the data generation code which uses real time apis as well as physics based rules to make semi synthetic data at the moment


When you want to listen to the data coming from the supabase database, run the following command:

# risk_agent.py  
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/ingest")
async def ingest(request: Request):
    row = await request.json()
    
    # This is the complete window_features row
    print("[RISK AGENT] Received:")
    print(f"  window_id     : {row['window_id']}")
    print(f"  shipment_id   : {row['shipment_id']}")
    print(f"  avg_temp_c    : {row['avg_temp_c']}")
    print(f"  delay_min     : {row['current_delay_min']}")
    print(f"  spoilage_risk : {row['target_spoilage_risk_6h']}")
    print(f"  full row      : {row}")

    # Rahul plugs his risk model in here
    # risk_score = his_model.predict(row)

    return {
        "risk_score": 74.0,       # placeholder return the actual data
        "risk_level": "HIGH",
        "explanation": "Temperature above threshold with customs delay"
    }


This is for the code calculating the risk 




The following code gets the risk from the supabase

# get_risk_data.py
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

<!-- All risk scores -->
results = sb.table("risk_scores").select("*").execute()

for row in results.data:
    print(f"window: {row['window_id']} | shipment: {row['shipment_id']} | "
          f"score: {row['risk_score']} | level: {row['risk_level']} | "
          f"reason: {row['explanation']}")



The following code gets live risk updates from the supabase

# downstream_listener.py  
import os, asyncio
from supabase._async.client import create_client
from dotenv import load_dotenv

load_dotenv()

def on_new_risk(payload: dict):
    record     = payload.get("data", {}).get("record", {})
    level      = record.get("risk_level")
    shipment   = record.get("shipment_id")
    score      = record.get("risk_score")
    explanation = record.get("explanation")

    print(f"[RISK UPDATE] shipment={shipment} | level={level} | score={score}")
    print(f"  reason: {explanation}")

   <!-- Each agent can do their own thing here that is run what needs to be done here -->

async def main():
    sb = await create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    channel = sb.channel("risk-stream")
    channel.on_postgres_changes(
        event="INSERT",
        schema="public",
        table="risk_scores",
        callback=on_new_risk,
    )
    await channel.subscribe()
    print("[DOWNSTREAM] Listening to risk_scores...\n")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())