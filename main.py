"""
Generic Billing Reconciliation Agent — Entry Point

Usage:
    python main.py --prompt "I want to do ACH reconciliation. In input/bank_recon.xlsx ..."
    python main.py  (interactive prompt)
    python main.py --prompt "..." --output output/my_run
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

_azure_vars    = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")
_has_azure     = all(os.environ.get(v) for v in _azure_vars)
_has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))

if not _has_azure and not _has_anthropic:
    print("ERROR: No LLM provider configured.")
    print("Set ANTHROPIC_API_KEY  — OR —")
    print("Set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT")
    sys.exit(1)

from src.agents.billing_agent import BillingReconAgent


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generic Billing Reconciliation Agent — reconcile any two data sources "
            "in any Excel workbook using a natural language prompt."
        )
    )
    parser.add_argument(
        "--prompt",
        default="",
        help=(
            "Natural language reconciliation instruction. "
            'Example: "I want to do ACH reconciliation. In input/bank_recon.xlsx, '
            'match the AR sheet Check+Amount+Date against ACH-JP sheet, '
            'fill Bank=JP, Bank date from ACH-JP Date, Amount Cleared from ACH-JP Amount."'
        ),
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory for the reconciliation report (default: output)",
    )
    args = parser.parse_args()

    user_prompt = args.prompt.strip()
    if not user_prompt:
        print("Generic Billing Reconciliation Agent")
        print("-" * 40)
        print("Enter your reconciliation instruction (or Ctrl+C to exit):")
        print()
        try:
            user_prompt = input("Prompt: ").strip()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)

    if not user_prompt:
        print("ERROR: No prompt provided.")
        sys.exit(1)

    agent  = BillingReconAgent(user_prompt=user_prompt, output_dir=args.output)
    result = agent.run()

    if result.get("output_file"):
        print(f"\nReport saved to: {result['output_file']}")
    else:
        print("\nAgent finished — no report path returned.")


if __name__ == "__main__":
    main()
