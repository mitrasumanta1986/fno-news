import io
import zipfile

from nse.fo_activity import parse_fo_bhavcopy
from nse.fo_universe import parse_fo_mktlots
from nse.prices import parse_cm_bhavcopy, parse_index_close
from nse.reference import parse_index_list

FO_LOTS = """UNDERLYING                          ,SYMBOL    ,SEP-26     ,OCT-26     ,
NIFTY 50                            ,NIFTY     ,65         ,65         ,
NIFTY BANK                          ,BANKNIFTY ,30         ,30         ,
Derivatives on Individual Securities,          ,           ,           ,
360 ONE WAM LIMITED                 ,360ONE    ,500        ,500        ,
HDFC BANK LIMITED                   ,HDFCBANK  ,           ,550        ,
"""

UDIFF_HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
                "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
                "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("file.csv", text)
    return buf.getvalue()


def test_fo_mktlots_excludes_indices_and_headers():
    entries = {e.symbol: e for e in parse_fo_mktlots(FO_LOTS)}
    assert set(entries) == {"360ONE", "HDFCBANK"}
    assert entries["360ONE"].lot_size == 500
    assert entries["HDFCBANK"].lot_size == 550  # first non-empty month
    assert entries["HDFCBANK"].underlying == "Hdfc Bank Limited"


def test_cm_bhavcopy_filters_series_and_symbols():
    rows = "\n".join([
        UDIFF_HEADER,
        "2026-09-25,2026-09-25,CM,NSE,STK,1,INE1,HDFCBANK,EQ,,,,,HDFC BANK,1000,1010,990,1005.5,1005,1000,,1005.5,,,12345,1,1,F1,1,,,,,",
        "2026-09-25,2026-09-25,CM,NSE,STK,2,INE2,HDFCBANK,N1,,,,,HDFC BANK NCD,1,1,1,1,1,1,,1,,,1,1,1,F1,1,,,,,",
        "2026-09-25,2026-09-25,CM,NSE,STK,3,INE3,OTHER,EQ,,,,,OTHER,1,1,1,1,1,1,,1,,,1,1,1,F1,1,,,,,",
    ])
    out = parse_cm_bhavcopy(_zip(rows), {"HDFCBANK": 7})
    assert len(out) == 1 and out[0]["stock_id"] == 7 and out[0]["close"] == 1005.5 and out[0]["volume"] == 12345


def test_fo_bhavcopy_aggregates_per_underlying():
    rows = "\n".join([
        UDIFF_HEADER,
        "2026-09-25,2026-09-25,FO,NSE,STF,1,,RELIANCE,,2026-10-27,,,,X,1,1,1,1,1,1,1226,1,500000,1000,200,1000000,1,F1,500,,,,,",
        "2026-09-25,2026-09-25,FO,NSE,STO,2,,RELIANCE,,2026-10-27,,1300,CE,X,1,1,1,1,1,1,1226,1,1000000,-500,300,2000000,1,F1,500,,,,,",
        "2026-09-25,2026-09-25,FO,NSE,IDO,3,,NIFTY,,2026-10-27,,1,CE,X,1,1,1,1,1,1,1,1,9999999,0,999,9,1,F1,65,,,,,",
    ])
    out = parse_fo_bhavcopy(_zip(rows), {"RELIANCE": 3})
    assert len(out) == 1
    r = out[0]
    assert r["fut_oi"] == 500000 and r["opt_oi"] == 1000000 and r["oi_contracts"] == 3000
    assert r["total_contracts"] == 500 and r["turnover"] == 3000000 and r["oi_change"] == 500


def test_index_close_and_reference_parsers():
    idx = parse_index_close("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
                            "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
                            "Nifty 50,25-09-2026,23035,23162.7,23020.95,23140.5,77.4,.34,1,1,1,1,1\n")
    assert idx == [{"index_name": "Nifty 50", "trade_date": "2026-09-25", "close": 23140.5, "change": 77.4,
                    "change_pct": 0.34, "source": "NSE indices (EOD)"}]
    ref = parse_index_list("Company Name,Industry,Symbol,Series,ISIN Code\nHDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034\n")
    assert ref["HDFCBANK"] == {"name": "HDFC Bank Ltd.", "sector": "Financial Services", "isin": "INE040A01034"}


def test_parse_all_indices_maps_names_and_uses_official_values():
    from nse.live_indices import parse_all_indices

    payload = {"timestamp": "01-Oct-2026 15:30", "data": [
        {"index": "NIFTY NEXT 50", "last": 68981.35, "previousClose": 69746.95, "percentChange": -1.1,
         "high": 69683.9, "low": 68110.5},
        {"index": "INDIA VIX", "last": 14.44, "previousClose": 13.49, "percentChange": 7.04, "high": 15.69, "low": 13.49},
        {"index": "", "last": 1},
    ]}
    rows = parse_all_indices(payload, ["Nifty Next 50", "India VIX"])
    assert [r["index_name"] for r in rows] == ["Nifty Next 50", "India VIX"]
    assert rows[0]["session_date"] == "2026-10-01" and rows[0]["bar_time"].startswith("2026-10-01T10:00")
    assert rows[1]["prev_close"] == 13.49 and rows[1]["change_pct"] == 7.04


def test_rebase_prev_close_uses_official_close():
    from technical.intraday import rebase_prev_close

    snap = rebase_prev_close({"last": 14.435, "prev_close": 13.4625, "change_pct": 7.22}, 13.49)
    assert snap["prev_close"] == 13.49 and round(snap["change_pct"], 2) == 7.01
