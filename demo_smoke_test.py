"""
Demo smoke test - SmithAgenticAIChallenge
Pharmaceutical Cold Chain Risk Intelligence

Runs the full cascade in sequence:
  1. Triage - rank at-risk shipments from real scored data
  2. Route agent - live weather + Groq LLM reasoning
  3. Insurance agent - real excursion data + itemised loss
  4. Triage output shows what to pass to orchestrator

This is the demo script. Run with:
  .venv/Scripts/python demo_smoke_test.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')

# Load .env
env_path = Path('.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

import pandas as pd

DIVIDER = "=" * 65


def header(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def section(title):
    print(f"\n--- {title} ---")


def run_demo():
    print(f"\n{'='*65}")
    print("  SMITH AGENTIC AI CHALLENGE")
    print("  Pharmaceutical Cold Chain Risk Intelligence - Demo Run")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*65}")

    groq_key = os.environ.get('GROQ_API_KEY', '')
    if not groq_key or groq_key == 'your_key_here':
        print('\n  WARNING: No GROQ_API_KEY set in .env')
        print('  Route agent will use deterministic fallback (no LLM reasoning)')
        print('  Add your Groq key to .env to enable live LLM reasoning\n')

    # ----------------------------------------------------------------
    # STEP 1: TRIAGE - rank at-risk shipments
    # ----------------------------------------------------------------
    header("STEP 1 - TRIAGE: Rank At-Risk Shipments")

    from tools.triage_agent import _execute as triage_execute

    df = pd.read_csv('artifacts/scored_windows.csv')
    at_risk = df[df['risk_tier'].isin(['CRITICAL', 'HIGH'])]
    worst = (
        at_risk.sort_values('final_score', ascending=False)
        .drop_duplicates('shipment_id')
        .head(5)
    )

    shipments_input = [
        {
            'shipment_id': str(r['shipment_id']),
            'risk_tier': str(r['risk_tier']),
            'fused_risk_score': float(r['final_score']),
            'product_id': str(r['product_id']),
            'container_id': str(r.get('container_id', '')),
            'transit_phase': str(r.get('transit_phase', '')),
        }
        for _, r in worst.iterrows()
    ]

    triage_result = triage_execute(shipments=shipments_input, enrich=True)

    print(f"\n  {triage_result['total_shipments']} shipments ranked | "
          f"{triage_result['critical_count']} CRITICAL | "
          f"{triage_result['high_count']} HIGH")
    print(f"\n  {'RANK':<5} {'SHIPMENT':<10} {'PRODUCT':<30} {'TIER':<10} {'SCORE':<8} {'HRS AT RISK':<12} {'PEAK TEMP'}")
    print(f"  {'-'*5} {'-'*10} {'-'*30} {'-'*10} {'-'*8} {'-'*12} {'-'*10}")

    for item in triage_result['priority_list']:
        hrs = f"{item['hours_at_risk']}h" if item['hours_at_risk'] else "n/a"
        peak = f"{item['peak_temp_c']}C" if item['peak_temp_c'] else "n/a"
        print(f"  {item['priority_rank']:<5} {item['shipment_id']:<10} "
              f"{item['product_name'][:28]:<30} {item['risk_tier']:<10} "
              f"{item['fused_risk_score']:<8.3f} {hrs:<12} {peak}")

    print(f"\n  Recommended orchestration order: {triage_result['recommended_orchestration_order']}")

    # Pick top shipment for cascade
    top = triage_result['priority_list'][0]
    top_shipment = top['shipment_id']
    top_product = top['product_id']
    top_leg = df[df['shipment_id'] == top_shipment]['leg_id'].iloc[0]
    top_row = worst[worst['shipment_id'] == top_shipment].iloc[0]

    # ----------------------------------------------------------------
    # STEP 2: ROUTE AGENT - live weather + LLM reasoning
    # ----------------------------------------------------------------
    header(f"STEP 2 - ROUTE AGENT: Shipment {top_shipment} ({top_product})")

    from tools.route_agent import _execute as route_execute

    # Load facility for this product
    with open('data/facilities.json') as f:
        facilities = json.load(f)
    facility = facilities.get(top_product, {})

    route_result = route_execute(
        shipment_id=top_shipment,
        container_id=str(top_row.get('container_id', '')),
        current_leg_id=top_leg,
        reason=f"CRITICAL temperature excursion - {top['product_name']}",
        product_id=top_product,
        preferred_mode='air',
        risk_tier=str(top_row['risk_tier']),
        hours_to_breach=0.0,
        delay_class='developing',
        avg_temp_c=float(top_row['avg_temp_c']),
        temp_slope_c_per_hr=float(top_row['temp_slope_c_per_hr']),
        transit_phase=str(top_row.get('transit_phase', '')),
        det_rules_fired=str(top_row.get('det_rules_fired', '')).split(';'),
        facility=facility,
    )

    weather = route_result['weather_at_destination']
    print(f"\n  Product:      {top['product_name']} ({top_product})")
    print(f"  Temp class:   {route_result['temp_class'].upper()}")
    print(f"\n  LIVE WEATHER AT DESTINATION")
    print(f"  Facility:     {weather['facility_name']}")
    print(f"  Location:     {weather['location']}")
    print(f"  Conditions:   {weather['weather_description']}, {weather['temperature_c']}C, wind {weather['wind_speed_mph']}mph")
    print(f"  Severe alert: {'YES [!]' if weather['is_severe_weather'] else 'No'}")
    print(f"  Data source:  {weather['data_source']}")
    print(f"\n  RECOMMENDATION")
    print(f"  Route:        {route_result['recommended_route']}")
    print(f"  Carrier:      {route_result['carrier']}")
    print(f"  ETA change:   {route_result['eta_change_hours']:+d} hours")
    print(f"  Reasoning:    {route_result.get('reasoning_source', 'unknown')}")
    if route_result.get('model_used'):
        print(f"  Model:        {route_result['model_used']}")
    print(f"\n  JUSTIFICATION")
    print(f"  {route_result['justification']}")
    print(f"\n  Requires approval: {route_result['requires_approval']}")

    # ----------------------------------------------------------------
    # STEP 3: INSURANCE AGENT - real excursion data
    # ----------------------------------------------------------------
    header(f"STEP 3 - INSURANCE AGENT: Claim for {top_shipment}")

    from tools.insurance_agent import _execute as ins_execute

    ins_result = ins_execute(
        shipment_id=top_shipment,
        container_id=str(top_row.get('container_id', '')),
        product_id=top_product,
        risk_tier='CRITICAL',
        incident_summary=(
            f"Temperature excursion confirmed on {top['product_name']}. "
            f"{top['hours_at_risk']} hours at risk. "
            f"Peak temperature {top['peak_temp_c']}C recorded. "
            f"Primary breach rule: {top['primary_breach_rule']}."
        ),
        leg_id=top_leg,
        spoilage_probability=float(top_row['ml_score']),
        supporting_evidence=[f"triage_rank_{top['priority_rank']}", f"route_rec_{route_result['carrier']}"],
    )

    exc = ins_result['excursion_summary']
    lb = ins_result['loss_breakdown']

    print(f"\n  Claim ID:     {ins_result['claim_id']}")
    print(f"  Product:      {ins_result['product_name']}")
    print(f"  Regulatory:   {ins_result['regulatory_class']}")
    print(f"\n  EXCURSION EVIDENCE (from real scored telemetry)")
    print(f"  Windows analysed:   {exc.get('windows_analysed', 0)}")
    print(f"  Windows in breach:  {exc.get('windows_in_breach', 0)}")
    print(f"  Total excursion:    {exc.get('total_excursion_min', 0)} minutes")
    print(f"  Peak temperature:   {exc.get('peak_temp_c')}C")
    print(f"\n  ITEMISED LOSS ESTIMATE")
    print(f"  Product loss:           ${lb.get('product_loss_usd', 0):>12,.2f}")
    print(f"  Disposal cost:          ${lb.get('disposal_cost_usd', 0):>12,.2f}")
    print(f"  Downstream disruption:  ${lb.get('downstream_disruption_usd', 0):>12,.2f}")
    print(f"  Handling (sunk):        ${lb.get('handling_cost_usd', 0):>12,.2f}")
    print(f"  Risk multiplier:        {lb.get('risk_multiplier', 1.0)}x")
    print(f"  {'-'*40}")
    print(f"  TOTAL ESTIMATED LOSS:   ${ins_result['estimated_loss_usd']:>12,.2f}")
    print(f"\n  Next steps:")
    for step in ins_result['next_steps']:
        print(f"    * {step}")
    print(f"\n  Requires approval: {ins_result['requires_approval']}")

    # ----------------------------------------------------------------
    # SUMMARY
    # ----------------------------------------------------------------
    header("DEMO COMPLETE - Cascade Summary")

    groq_fired = route_result.get('reasoning_source') == 'groq_llm'
    weather_live = weather.get('data_source') == 'Open-Meteo live'

    print(f"\n  Shipment:         {top_shipment} ({top_product} - {top['product_name']})")
    print(f"  Risk tier:        CRITICAL")
    print(f"  Hours at risk:    {top['hours_at_risk']}h")
    print(f"  Peak temp:        {top['peak_temp_c']}C")
    print(f"\n  Triage:           {triage_result['total_shipments']} shipments ranked from real data")
    print(f"  Weather fetch:    {'LIVE (Open-Meteo)' if weather_live else 'unavailable'}")
    print(f"  LLM reasoning:    {'Groq ' + route_result.get('model_used','') if groq_fired else 'deterministic fallback'}")
    print(f"  Carrier selected: {route_result['carrier']}")
    print(f"  ETA improvement:  {route_result['eta_change_hours']:+d} hours")
    print(f"  Claim value:      ${ins_result['estimated_loss_usd']:,.2f}")
    print(f"  Approval queued:  Yes (route + insurance both require_approval=True)")
    print(f"\n{'='*65}\n")


if __name__ == '__main__':
    run_demo()
