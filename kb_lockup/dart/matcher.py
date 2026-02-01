
import logging
from typing import Dict, List, Optional
from kb_lockup.config import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

class OwnerMatcher:
    """
    Matches SEIBro unstaking rows to DART owner data.
    """
    
    def __init__(self):
        # Re-use settings
        api_key = settings.qwen_api_key or settings.dart_api_key
        base_url = settings.get_qwen_base_url()
        
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        else:
            self.client = None

    def find_owner_matches(self, seibro_shares: int, seibro_reason: str, vart_candidates: List[Dict], limit: int = 5) -> List[Dict[str, any]]:
        """
        Returns list of { "name": ..., "confidence": ..., "source": ..., "shares": ... }
        """
        if not vart_candidates:
            return []
            
        # 1. Volume Match Calculation
        scored_candidates = []
        for cand in vart_candidates:
            dart_shares = cand.get('shares', 0)
            if dart_shares == 0: continue
            
            diff_pct = abs(seibro_shares - dart_shares) / dart_shares
            
            vol_score = 0.0
            if diff_pct < 0.001: vol_score = 1.0     # < 0.1% diff
            elif diff_pct < 0.01: vol_score = 0.9    # < 1% diff
            elif diff_pct < 0.05: vol_score = 0.7    # < 5% diff
            elif diff_pct < 0.10: vol_score = 0.4    # < 10% diff
            
            # Simple heuristic: if name matches query or reason, big boost (not implemented here yet)
            
            scored_candidates.append({
                "name": cand.get('name'),
                "confidence": vol_score,
                "shares": dart_shares,
                "diff_pct": diff_pct,
                "source": "Volume Match",
                "relation": cand.get('relation')
            })
            
        # Sort by volume score
        scored_candidates.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Return top N
        return scored_candidates[:limit]
