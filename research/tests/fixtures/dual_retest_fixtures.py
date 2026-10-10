"""Portable synthetic snapshots matching the product's eight-news-item envelope."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from app.evidence_snapshot import create_content, snapshot_id

VERSION = 'dual_retest_fixture_v2'
FIXTURE_IDS = {'A': 'synthetic_production_v1_TESTCO', 'B': 'synthetic_adversarial_v1_TESTCO'}
INDICATORS = ('RSI14', 'EMA20', 'EMA50', 'SMA20', 'SMA50', 'MACD', 'MACD_SIGNAL',
              'BOLLINGER', 'ATR', 'ROC', 'VOLUME_SMA', 'VOLUME_SPIKE')
STORIES = (
    ('TESTCO announced a service partnership.', 'The fictional company announced a service partnership. The announcement describes service delivery, not a realized market return.', 'product', 'positive'),
    ('TESTCO discussed a possible expansion.', 'The fictional company discussed expansion options. No completed agreement or increase in customer demand has been established.', 'other', 'uncertain'),
    ('TESTCO scheduled an earnings briefing.', 'A fictional earnings briefing is scheduled. Revenue and earnings results are not supplied, so the schedule alone establishes no growth claim.', 'earnings', 'neutral'),
    ('TESTCO appointed an operations manager.', 'A fictional operations manager was appointed. The appointment supplies management context but does not establish a change in profitability.', 'management', 'neutral'),
    ('TESTCO published a compliance update.', 'A fictional routine compliance update was published. The bulletin contains no sanction or regulatory finding and establishes no adverse catalyst.', 'regulatory', 'neutral'),
    ('TESTCO reported a product maintenance window.', 'A fictional scheduled maintenance window was reported. No sales interruption or loss is established by the supplied operational notice.', 'product', 'neutral'),
    ('TESTCO hosted an industry discussion.', 'The fictional company hosted an industry discussion. The event provides sector context, not a verified change in the company outlook.', 'sector', 'neutral'),
    ('TESTCO published its governance calendar.', 'A fictional governance calendar was published. Calendar information provides administrative context without supporting a directional price forecast.', 'other', 'neutral'),
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def build_fixture(test: str, as_of: str) -> dict:
    """Fixed as_of is part of identity; never silently refresh a frozen snapshot."""
    if test not in FIXTURE_IDS:
        raise ValueError('Unknown synthetic test')
    parsed = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone is required')
    stamp = parsed.astimezone(timezone.utc).isoformat()
    key = VERSION + ':' + test
    prices = (58, 101, 99, 100.5, 98.5, 0.6, 0.4, 100, 1.4, 1.1, 100000, 1.2)
    if test == 'B':
        prices = (44, 99, 101, 99.5, 102, -0.4, -0.2, 100, 3.5, -0.8, 100000, 1.8)
    indicators = []
    for name, value in zip(INDICATORS, prices):
        descriptive = name in ('BOLLINGER', 'ATR', 'VOLUME_SMA')
        indicators.append({'indicator': name, 'value': value,
            'signal': 'neutral' if descriptive else 'bullish' if test == 'A' else 'bearish',
            'strength': 0.25 if descriptive else 0.55,
            'reason': 'Descriptive state, not independent directional evidence.' if descriptive else
                      'Upward trend context.' if test == 'A' else 'Downward momentum context.'})
    articles = []
    for i, (title, summary, kind, cue) in enumerate(STORIES):
        if test == 'A' and i == 1:
            title = 'TESTCO discussed service delivery planning.'
            summary = 'The fictional company discussed routine service delivery planning. No material demand change or completed expansion is established.'
            cue = 'neutral'
        articles.append({'id': f'{test}-story-{i}', 'symbol': 'NSE:TESTCO', 'title': title,
            'summary': summary, 'source': 'Synthetic company bulletin',
            'url': f'https://example.org/synthetic/{test}/story-{i}', 'published_at': stamp,
            'source_quality': 0.85 if i != 1 else 0.45,
            'event_type': kind, 'relevance': 0.8 if i == 0 else 0.2 if test == 'B' and i == 1 else 0.5,
            'sentiment': cue, 'provenance': {'provider': 'synthetic'}})
    events = [{'event_id': f'{test}-event-{i}', 'event_type': a['event_type'],
        'direction': 'BULLISH' if i == 0 else 'NEUTRAL', 'impact': 0.25 if i == 0 else 0.0,
        'headline': a['title'], 'url': a['url'], 'sources': [a['source']], 'article_ids': [a['id']],
        'flags': ['UNCONFIRMED_CONTEXT'] if test == 'B' and i == 1 else []}
        for i, a in enumerate(articles)]
    market = {'symbol': 'TESTCO.NS', 'capture_id': digest(key + ':capture'),
        'provider': 'synthetic', 'retrieved_at': stamp, 'quality': {'state': 'PASS'},
        'bronze': {'sha256': digest(key + ':bronze')}, 'silver': {'sha256': digest(key + ':silver')},
        'gold': {'sha256': digest(key + ':technical-gold')}, 'provenance': {'cache_hit': False}}
    technicals = {'as_of': stamp, 'indicators': indicators,
        'trend': 'bullish' if test == 'A' else 'bearish',
        'regime': 'TRENDING_BULL' if test == 'A' else 'HIGH_VOLATILITY'}
    summary = {'model': 'NeoQuasar/Kronos-base', 'input_rows': 256, 'forecast_rows': 24,
        'sampling_T': 0.85, 'sampling_top_k': 0, 'sampling_top_p': 0.90, 'sample_count': 1,
        'direction': 'up', 'last_observed_close': 100.0, 'forecast_final_close': 101.2,
        'forecast_pct_change': 1.2}
    news = {'events': articles, 'provider': 'synthetic', 'providers_used': ['synthetic'],
        'retrieved_at': stamp, 'cache_status': 'synthetic_fixture',
        'news_pipeline': {'bronze_hashes': [digest(key + ':news-bronze')]}}
    impact = {'events': events, 'score': 0.25 if test == 'A' else 0.18,
        'uncertainty_flags': [] if test == 'A' else ['Weak discussion is unconfirmed; contextual cues are not measured price impact.'],
        'analysis_version': 'synthetic_news_impact_v1'}
    outlook = {'preliminary_research_view': 'BULLISH' if test == 'A' else 'MIXED',
        'confidence': 'MEDIUM' if test == 'A' else 'LOW', 'status': 'CONTEXT_ONLY',
        'analysis_version': 'synthetic_research_view_v1',
        'supporting_evidence': ['Kronos direction is up.'],
        'contradicting_evidence': [] if test == 'A' else ['Technical trend is bearish.'],
        'primary_risk': 'Forecast may not match realized market path.' if test == 'A' else
                        'Elevated volatility and conflicting evidence limit support.',
        'why': 'Kronos and technical trend align; news is contextual.' if test == 'A' else
               'Kronos and technical trend disagree; weak news and elevated volatility limit support.'}
    content = create_content(symbol='TESTCO.NS', exchange='NSE', summary=summary,
        fingerprint=digest(key + ':forecast'), forecast_sha256=digest(key + ':forecast-bytes'),
        input_sha256=digest(key + ':input'), market=market, technicals=technicals,
        news=news, impact=impact, outlook=outlook,
        news_gold={'sha256': digest(key + ':news-gold')}, technical_version='synthetic_technical_v1')
    pipeline = {'stages': {s: {'status': 'HEALTHY', 'last_update': stamp,
        'rows': 8 if s == 'news' else 256, 'warnings': [], 'errors': [],
        'provider': 'synthetic', 'cache_status': 'fixture'} for s in ('bronze', 'silver', 'gold', 'news')}}
    return {'fixture_id': FIXTURE_IDS[test], 'fixture_version': VERSION, 'test': test,
        'synthetic_only': True, 'record': {'evidence': content, 'snapshot_id': snapshot_id(content),
                                          'created_at': stamp}, 'pipeline': pipeline}
