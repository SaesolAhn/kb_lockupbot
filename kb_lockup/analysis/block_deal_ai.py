import logging
import json
from typing import Dict, Any, Optional

from openai import OpenAI
from kb_lockup.config import settings

logger = logging.getLogger(__name__)

class BlockDealAnalyzer:
    """
    Analyzes unstaking events to assess the probability of a block deal.
    """
    
    def __init__(self):
        # Assuming OpenAI client is compatible or use standard
        # If settings.qwen_api_key is set (from config.py inspection), we might use compatible endpoint?
        # The config has qwen_api_key and qwen_base_url.
        # Let's try to use that configuration if available, else generic OpenAI.
        
        api_key = settings.qwen_api_key or settings.dart_api_key # Fallback or error if missing
        base_url = settings.get_qwen_base_url()
        
        if not api_key:
             logger.warning("No API key found for AI analysis. Block deal scoring will be skipped.")
             self.client = None
        else:    
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None
            )

    def analyze_row(self, row: Dict[str, Any]) -> tuple[Optional[int], Optional[str]]:
        """
        Analyzes a single row and returns (score, explanation).
        Score: 0-100 (Higher = Higher chance of Block Deal/Overhang)
        """
        if not self.client:
            return None, "AI Client not initialized"

        # Prepare context for LLM
        company = row.get('company_name')
        owner = row.get('reason') # Using 'reason' as proxy for owner type since specific owner name might not be in table
        # Table has 'reason' (e.g. VC, Max Shareholder) but not 'owner' name column in seibro table explicitly?
        # Actually seibro table has 'reason' which often contains "Blue Run Ventures" etc or just "Voluntary Lockup".
        # Wait, the parser mapped 'reason' to what? "의무보유사유". 
        # The prompt said "reason" is "의무보유사유".
        
        shares = row.get('return_shares', 0)
        total_shares = row.get('total_shares', 1)
        stake_pct = row.get('stake_portion_pct')
        value_krw = row.get('current_stake_value_million_krw')
        
        if not value_krw or value_krw < 100: # Ignore very small amounts (< 100M KRW)
            return 10, "Amount too small for significant block deal risk."

        prompt = f"""
You are a financial analyst specializing in Korean customized block deals. Assess the likelihood of a Block Deal (bulk sale) for the following unstaking event.

Data:
- Company: {company}
- Unstaking Reason/Holder Type: {owner}
- Shares: {shares:,}
- Stake Portion: {stake_pct}% of total shares
- Estimated Value: {value_krw:,.0f} Million KRW

Guidelines:
- High Risk (Score 80-100): VC/PEF exiting, very large stake (>3% or >10B KRW), financial investors.
- Medium Risk (50-79): Significant stake but maybe strategic partner or employee stock options.
- Low Risk (0-49): Founder/Executive (likely to hold), small stake, or protective deposit.

Return JSON only:
{{
  "score": <0-100 integer>,
  "reason": "<short explanation within 20 words>"
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=settings.qwen_model or "gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a financial risk assessor. Output JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            content = response.choices[0].message.content
            # Strip code blocks if present
            if "```" in content:
                content = content.replace("```json", "").replace("```", "")
                
            data = json.loads(content)
            return data.get("score"), data.get("reason")
            
        except Exception as e:
            logger.error(f"AI Analysis failed for {company}: {e}")
            return None, f"Analysis Error: {str(e)}"
