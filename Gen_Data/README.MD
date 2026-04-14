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

