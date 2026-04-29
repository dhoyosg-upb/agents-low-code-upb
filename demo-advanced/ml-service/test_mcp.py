"""Smoke test del servidor MCP local."""
import asyncio
from fastmcp import Client


async def main():
    async with Client("http://localhost:8000/mcp/") as c:
        tools = await c.list_tools()
        print("=== MCP TOOLS DISPONIBLES ===")
        for t in tools:
            desc = (t.description or "").split("\n")[0][:80]
            print(f"  - {t.name}: {desc}")
        print()

        emails = [
            "daniel.hoyosg@upb.edu.co",
            "ana.premium@demo.com",
            "carlos.toxico@demo.com",
            "maria.inactiva@demo.com",
            "pedro.moroso@demo.com",
        ]
        print("=== predict_churn_risk ===")
        for email in emails:
            r = await c.call_tool("predict_churn_risk", {"email": email})
            d = r.data
            print(f"  {email:32s} prob={d['churn_probability']:.3f} risk={d['risk_level']:6s} ({d['name']})")

        print("\n=== get_payment_history (Pedro Moroso) ===")
        r = await c.call_tool("get_payment_history", {"email": "pedro.moroso@demo.com"})
        d = r.data
        print(f"  plan={d['plan_type']}  monthly=${d['monthly_charge_usd']}  debt=${d['current_debt_usd']}  in_collections={d['in_collections']}")
        print(f"  on_time_pct={d['summary_12m']['on_time_pct']}  late={d['summary_12m']['late_payments']}")

        print("\n=== get_support_history (Daniel) ===")
        r = await c.call_tool("get_support_history", {"email": "daniel.hoyosg@upb.edu.co"})
        d = r.data
        print(f"  channel={d['preferred_channel']}  complaints_90d={d['num_complaints_90d']}  calls_30d={d['support_calls_30d']}")
        print(f"  last_complaint: {d['last_complaint_text']}")


if __name__ == "__main__":
    asyncio.run(main())
