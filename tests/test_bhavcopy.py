"""Bhavcopy client against the current official file formats (headers copied
from the real BSE UDiFF and NSE price-report files of 28 Oct 2026)."""

import io
import zipfile
from datetime import date
from unittest.mock import MagicMock

from market_data.bhavcopy import BhavcopyClient
from market_data.resolver import BhavcopyMarketResolver

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    "2026-10-28,2026-10-28,CM,BSE,STK,512599,INE423A01024,ADANIENT,A,,,,,ADANI,"
    "1.00,1.00,1.00,2400.50,2400.50,1.00,,1.00,,,1,1.00,1,F1,1,,,,,\n"
    "2026-10-28,2026-10-28,CM,BSE,STK,532921,INE742F01042,ADANIPORTS,A,,,,,"
    "ADANI PORTS AND SPECIAL ECONOMIC ZONE,1.00,1.00,1.00,1350.25,1350.25,1.00,,1.00,,,1,1.00,1,F1,1,,,,,\n"
)

MCAP = (
    "Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),"
    "Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)              \n"
    # Name does not match exactly; a name prefix would point at ADANIENT.
    "28 OCT 2026,ADANIPORTS,EQ,ADANI PORTS & SEZ    ,Listed    ,28 OCT 2026,  2.00,"
    "  2160000000,  1350.00,  2916000000000.00       \n"
    "28 OCT 2026,ADANIENT,EQ,ADANI ENTERPRISES    ,Listed    ,28 OCT 2026,  1.00,"
    "  1154000000,  2400.00,  2769600000000.00       \n"
    # No BSE ticker: falls to the fuzzy name match, which must not override.
    "28 OCT 2026,ADANIGREEN,EQ,ADANI GREEN ENERGY   ,Listed    ,28 OCT 2026,  10.00,"
    "  1584000000,  1000.00,  1584000000000.00       \n"
)


def _response(status=200, text="", content=b""):
    response = MagicMock(status_code=status, text=text, content=content)
    response.raise_for_status.return_value = None
    return response


def _pr_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mcap28102026.csv", MCAP)
        archive.writestr("Pr281026.csv", "not used")
    return buffer.getvalue()


def _client():
    session = MagicMock()
    session.headers = {}

    def get(url, timeout):
        if url.endswith("BhavCopy_BSE_CM_0_0_0_20261028_F_0000.CSV"):
            return _response(text=UDIFF)
        if url.endswith("/pr/PR281026.zip"):
            return _response(content=_pr_zip())
        return _response(status=404)

    session.get.side_effect = get
    return BhavcopyClient(session=session), session


def test_udiff_bse_file_is_parsed():
    client, _ = _client()
    records = client.fetch_bse_equity(date(2026, 10, 28))
    assert set(records) == {"512599", "532921"}
    ports = records["532921"]
    assert (ports.isin, ports.close, ports.ticker) == ("INE742F01042", 1350.25, "ADANIPORTS")


def test_nse_caps_come_from_the_price_report_and_match_exact_tickers():
    client, _ = _client()
    client.fetch_bse_equity(date(2026, 10, 28))
    caps = client.fetch_nse_market_caps(date(2026, 10, 28))
    # Exact ticker matches, not the "ADANI" name prefix and not ADANIGREEN.
    assert caps["INE742F01042"] == 2916000000000.0
    assert caps["INE423A01024"] == 2769600000000.0


def test_resolver_returns_cap_and_price_for_a_bse_code():
    client, _ = _client()
    resolver = BhavcopyMarketResolver(client=client, lookback_days=1)
    assert resolver.resolve("532921", date(2026, 10, 28)) == (2916000000000.0, 1350.25)
