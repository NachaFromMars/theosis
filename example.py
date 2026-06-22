"""Quick demo: run Theosis with mock slots (no API key needed)."""
import asyncio
from theosis import theosis, ModelSlot

async def main():
    slots = [
        ModelSlot.mock("alpha"),
        ModelSlot.mock("beta"),
        ModelSlot.mock("gamma"),
    ]
    aggregator = ModelSlot.mock("aggregator", model="mock-agg")

    def on_event(event):
        print(f"[{event['type']}]", {k: v for k, v in event.items() if k != "type"})
        return asyncio.sleep(0)

    final, trail = await theosis(
        request="Explain the fan-out → audit → patch → merge pipeline in one paragraph.",
        slots=slots,
        aggregator=aggregator,
        max_rounds=1,
        on_event=on_event,
    )
    print("\n=== FINAL ANSWER ===")
    print(final)

if __name__ == "__main__":
    asyncio.run(main())
