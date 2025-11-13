"""
Fetch Russell 1000 tickers from various sources
"""
import requests
import pandas as pd
from bs4 import BeautifulSoup

def fetch_russell1000_tickers():
    """
    Fetch Russell 1000 component tickers
    
    Sources:
    1. Wikipedia Russell 1000 page
    2. Marketvolume.com 
    3. Fallback to combining Nasdaq 100 + S&P 500 + additional large caps
    """
    
    all_tickers = set()
    
    # Method 1: Try Wikipedia
    try:
        url = "https://en.wikipedia.org/wiki/Russell_1000_Index"
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for ticker symbols in tables
        tables = soup.find_all('table', {'class': 'wikitable'})
        for table in tables:
            rows = table.find_all('tr')
            for row in rows[1:]:  # Skip header
                cells = row.find_all('td')
                if len(cells) >= 2:
                    ticker = cells[0].text.strip()
                    if ticker and len(ticker) <= 5:  # Basic validation
                        all_tickers.add(ticker)
        
        print(f"Wikipedia: Found {len(all_tickers)} tickers")
    except Exception as e:
        print(f"Wikipedia fetch failed: {e}")
    
    # Method 2: Try marketvolume.com
    try:
        url = "https://www.marketvolume.com/indexes_exchanges/r1000_components.asp"
        df = pd.read_html(url)[0]
        if 'Symbol' in df.columns:
            tickers = df['Symbol'].dropna().unique()
            all_tickers.update(tickers)
        print(f"Marketvolume: Total {len(all_tickers)} tickers")
    except Exception as e:
        print(f"Marketvolume fetch failed: {e}")
    
    # Method 3: Construct from known indices if needed
    if len(all_tickers) < 500:
        print("Using fallback: combining major indices...")
        
        # S&P 500 (largest 500)
        sp500 = [
            'A', 'AAL', 'AAPL', 'ABBV', 'ABC', 'ABMD', 'ABT', 'ACN', 'ADBE', 'ADI',
            'ADM', 'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG',
            'AKAM', 'ALB', 'ALGN', 'ALK', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME',
            'AMGN', 'AMP', 'AMT', 'AMZN', 'ANET', 'ANSS', 'AON', 'AOS', 'APA', 'APD',
            'APH', 'APTV', 'ARE', 'ATO', 'AVB', 'AVGO', 'AVY', 'AWK', 'AXP',
            'AZO', 'BA', 'BAC', 'BALL', 'BAX', 'BBWI', 'BBY', 'BDX', 'BEN', 'BF.B',
            'BIIB', 'BIO', 'BK', 'BKNG', 'BKR', 'BLK', 'BMY', 'BR', 'BRK.B', 'BRO',
            'BSX', 'BWA', 'BXP', 'C', 'CAG', 'CAH', 'CARR', 'CAT', 'CB', 'CBOE',
            'CBRE', 'CCI', 'CCL', 'CDNS', 'CDW', 'CE', 'CEG', 'CF', 'CFG',
            'CHD', 'CHRW', 'CHTR', 'CI', 'CINF', 'CL', 'CLX', 'CMA', 'CMCSA', 'CME',
            'CMG', 'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COO', 'COP', 'COST', 'CPB',
            'CPRT', 'CRL', 'CRM', 'CSCO', 'CSX', 'CTAS', 'CTLT', 'CTRA', 'CTSH',
            'CTVA', 'CVS', 'CVX', 'CZR', 'D', 'DAL', 'DD', 'DE', 'DFS', 'DG',
            'DGX', 'DHI', 'DHR', 'DIS', 'DLR', 'DLTR', 'DOV', 'DOW', 'DPZ', 'DRI',
            'DTE', 'DUK', 'DVA', 'DVN', 'DXCM', 'EA', 'EBAY', 'ECL', 'ED',
            'EFX', 'EIX', 'EL', 'ELV', 'EMN', 'EMR', 'ENPH', 'EOG', 'EPAM', 'EQIX',
            'EQR', 'ES', 'ESS', 'ETN', 'ETR', 'EVRG', 'EW', 'EXC', 'EXPD',
            'EXPE', 'EXR', 'F', 'FANG', 'FAST', 'FBHS', 'FCX', 'FDS', 'FDX', 'FE',
            'FFIV', 'FI', 'FICO', 'FIS', 'FITB', 'FLT', 'FMC', 'FOX', 'FOXA',
            'FRT', 'FSLR', 'FTNT', 'FTV', 'GD', 'GE', 'GILD', 'GIS', 'GL', 'GLW',
            'GM', 'GNRC', 'GOOG', 'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS', 'GWW',
            'HAL', 'HAS', 'HBAN', 'HCA', 'HD', 'HES', 'HIG', 'HII', 'HLT', 'HOLX',
            'HON', 'HPE', 'HPQ', 'HRL', 'HSIC', 'HST', 'HSY', 'HUBB', 'HUM', 'HWM',
            'IBM', 'ICE', 'IDXX', 'IEX', 'IFF', 'ILMN', 'INCY', 'INTC', 'INTU', 'INVH',
            'IP', 'IPG', 'IQV', 'IR', 'IRM', 'ISRG', 'IT', 'ITW', 'IVZ',
            'J', 'JBHT', 'JCI', 'JKHY', 'JNJ', 'JNPR', 'JPM', 'K', 'KDP', 'KEY',
            'KEYS', 'KHC', 'KIM', 'KLAC', 'KMB', 'KMI', 'KMX', 'KO', 'KR',
            'L', 'LDOS', 'LEN', 'LH', 'LHX', 'LIN', 'LKQ', 'LLY', 'LMT', 'LNC',
            'LNT', 'LOW', 'LRCX', 'LUMN', 'LUV', 'LVS', 'LW', 'LYB', 'LYV',
            'MA', 'MAA', 'MAR', 'MAS', 'MCD', 'MCHP', 'MCK', 'MCO', 'MDLZ', 'MDT',
            'MET', 'META', 'MGM', 'MHK', 'MKC', 'MKTX', 'MLM', 'MMC', 'MMM', 'MNST',
            'MO', 'MOH', 'MOS', 'MPC', 'MPWR', 'MRK', 'MRNA', 'MRO', 'MS', 'MSCI',
            'MSFT', 'MSI', 'MTB', 'MTCH', 'MTD', 'MU', 'NDAQ', 'NDSN', 'NEE', 'NEM',
            'NFLX', 'NI', 'NKE', 'NOC', 'NOW', 'NRG', 'NSC', 'NTAP', 'NTRS', 'NUE',
            'NVDA', 'NVR', 'NWS', 'NWSA', 'NXPI', 'O', 'ODFL', 'OKE', 'OMC', 'ON',
            'ORCL', 'ORLY', 'OTIS', 'OXY', 'PAYC', 'PAYX', 'PCAR', 'PCG', 'PEG',
            'PEP', 'PFE', 'PFG', 'PG', 'PGR', 'PH', 'PHM', 'PKG', 'PLD', 'PM',
            'PNC', 'PNR', 'PNW', 'PODD', 'POOL', 'PPG', 'PPL', 'PRU', 'PSA', 'PSX',
            'PTC', 'PWR', 'PXD', 'PYPL', 'QCOM', 'QRVO', 'RCL', 'RE', 'REG', 'REGN',
            'RF', 'RHI', 'RJF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG',
            'RTX', 'RVTY', 'SBAC', 'SBUX', 'SCHW', 'SHW', 'SJM', 'SLB', 'SNA', 'SNPS',
            'SO', 'SPG', 'SPGI', 'SRE', 'STE', 'STLD', 'STT', 'STX', 'STZ', 'SWK',
            'SWKS', 'SYF', 'SYK', 'SYY', 'T', 'TAP', 'TDG', 'TDY', 'TECH', 'TEL',
            'TER', 'TFC', 'TFX', 'TGT', 'TJX', 'TMO', 'TMUS', 'TPR', 'TRGP', 'TRMB',
            'TROW', 'TRV', 'TSCO', 'TSLA', 'TSN', 'TT', 'TTWO', 'TXN', 'TXT', 'TYL',
            'UAL', 'UDR', 'UHS', 'ULTA', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V',
            'VFC', 'VICI', 'VLO', 'VMC', 'VRSK', 'VRSN', 'VRTX', 'VTR', 'VTRS', 'VZ',
            'WAB', 'WAT', 'WBA', 'WBD', 'WDC', 'WEC', 'WELL', 'WFC', 'WM', 'WMB',
            'WMT', 'WRB', 'WRK', 'WST', 'WTW', 'WY', 'WYNN', 'XEL', 'XOM', 'XRAY',
            'XYL', 'YUM', 'ZBH', 'ZBRA', 'ZION', 'ZTS'
        ]
        
        # Additional large-cap growth stocks often in Russell 1000 but not S&P 500
        additional_large_caps = [
            'ABNB', 'ACGL', 'ACM', 'ADNT', 'AFG', 'AFRM', 'AGO', 'ALHC', 'ALNY', 
            'AMED', 'AMRC', 'AMRS', 'ANDV', 'APPN', 'ARCC', 'ARMK', 'ASGN', 'ASPN',
            'AYI', 'BC', 'BCPC', 'BEN', 'BERY', 'BG', 'BHF', 'BKNG', 'BLD', 'BMRN',
            'BNL', 'BOX', 'BRX', 'BURL', 'BXP', 'CABO', 'CADE', 'CACC', 'CAR', 'CBSH',
            'CCS', 'CDAY', 'CELG', 'CFR', 'CHE', 'CHGG', 'CHH', 'CHWY', 'CIT', 'CNHI',
            'CNK', 'CNO', 'COLM', 'CONE', 'CPRI', 'CPRT', 'CRS', 'CSGP', 'CUBE', 'CUZ',
            'CVNA', 'CVLT', 'CW', 'CWT', 'CWEN', 'DBX', 'DCI', 'DDOG', 'DDS', 'DECK',
            'DEI', 'DELL', 'DFIN', 'DKS', 'DLTR', 'DOC', 'DOCS', 'DOMO', 'DOCU', 'DRI',
            'DT', 'DV', 'DVA', 'EAT', 'EEFT', 'EGP', 'EHC', 'ELS', 'ENR', 'ENTG',
            'EPRT', 'EQC', 'ESNT', 'ESS', 'ESTC', 'ETH', 'EVH', 'EVR', 'EXP', 'FAF',
            'FBIN', 'FCN', 'FHN', 'FIVE', 'FL', 'FLO', 'FLS', 'FLT', 'FNB', 'FNF',
            'FR', 'FRSH', 'FRT', 'FSS', 'FUL', 'FWRD', 'GEN', 'GGG', 'GH', 'GHC',
            'GL', 'GLPI', 'GOLF', 'GPI', 'GPS', 'GRAM', 'GRFS', 'GRUB', 'GTLS', 'GXO',
            'H', 'HALO', 'HBI', 'HCP', 'HE', 'HELE', 'HIBB', 'HLF', 'HLI', 'HNI',
            'HOMB', 'HP', 'HRB', 'HRI', 'HTH', 'HTZ', 'HUBG', 'HUN', 'IAA', 'IAC',
            'IBP', 'INFO', 'IPGP', 'IPG', 'IRT', 'ITT', 'JBGS', 'JBL', 'JEF', 'JHG',
            'JLL', 'JMIA', 'JOUT', 'KAR', 'KEX', 'KFY', 'KN', 'KNX', 'KRC', 'KRG',
            'KSS', 'KTB', 'LAMR', 'LAZR', 'LC', 'LEA', 'LEG', 'LESL', 'LFUS', 'LH',
            'LITE', 'LIVN', 'LKQ', 'LNT', 'LPLA', 'LPX', 'LRN', 'LSI', 'LXP', 'LYFT',
            'M', 'MAC', 'MAN', 'MANH', 'MASI', 'MCY', 'MD', 'MDC', 'MEDP', 'MELI',
            'MFA', 'MIDD', 'MIK', 'MLI', 'MNST', 'MOD', 'MOG.A', 'MRC', 'MRVL', 'MSG',
            'MSGE', 'MTG', 'MTN', 'MTZ', 'MUR', 'MXIM', 'NBR', 'NCR', 'NFE', 'NLS',
            'NLY', 'NN', 'NNN', 'NOV', 'NPO', 'NRZ', 'NSA', 'NTB', 'NVT', 'NWL',
            'NWN', 'OC', 'ODP', 'OFC', 'OGE', 'OGS', 'OHI', 'OII', 'OLN', 'ORA',
            'OSK', 'OUT', 'OVV', 'OZK', 'PAG', 'PARA', 'PATK', 'PBCT', 'PBI', 'PBF',
            'PCTY', 'PDCE', 'PEB', 'PENN', 'PII', 'PINC', 'PK', 'PLNT', 'PNFP', 'PNM',
            'POR', 'POST', 'PRGO', 'PRSP', 'PSB', 'PSTG', 'PVH', 'PZN', 'QL', 'QRVO',
            'R', 'RAMP', 'RBA', 'RC', 'RDN', 'REXR', 'RGA', 'RH', 'RILY', 'RIOT',
            'RKT', 'RLI', 'RLJ', 'ROKU', 'RPRX', 'RRC', 'RRGB', 'RS', 'RST', 'RUTH',
            'RXN', 'SAGE', 'SAIC', 'SANM', 'SAM', 'SBH', 'SCCO', 'SEIC', 'SF', 'SFM',
            'SGEN', 'SGH', 'SIRI', 'SIX', 'SKT', 'SKX', 'SKY', 'SLG', 'SLM', 'SM',
            'SMCI', 'SMP', 'SNAP', 'SNV', 'SNX', 'SON', 'SPCE', 'SPR', 'SPOT', 'SQ',
            'SRC', 'SRCL', 'SSNC', 'SSL', 'ST', 'STAG', 'STER', 'STOR', 'STWD', 'SUI',
            'SUM', 'SUN', 'SUPN', 'TEAM', 'TECK', 'TELZ', 'TEX', 'TFSL', 'THG', 'THO',
            'TNET', 'TOL', 'TPH', 'TPL', 'TPX', 'TREX', 'TRI', 'TRIP', 'TRN', 'TRUP',
            'TSCO', 'TTC', 'TTD', 'TTWO', 'TW', 'TWO', 'TWTR', 'TX', 'TXRH', 'TXMD',
            'TYL', 'UBER', 'UE', 'UFPI', 'UGI', 'UPST', 'USFD', 'USLM', 'VAC', 'VC',
            'VLY', 'VNO', 'VNT', 'VOYA', 'VRE', 'VST', 'WDAY', 'WEN', 'WEX', 'WHR',
            'WING', 'WK', 'WLK', 'WNC', 'WPX', 'WRE', 'WRI', 'WSC', 'WSM', 'WSO',
            'WWE', 'WWW', 'X', 'XPO', 'XRAY', 'YETI', 'Z', 'ZEN', 'ZG', 'ZI', 'ZNGA'
        ]
        
        all_tickers.update(sp500)
        all_tickers.update(additional_large_caps)
        print(f"Fallback: {len(all_tickers)} tickers")
    
    # Clean and sort
    tickers_list = sorted(list(all_tickers))
    
    print(f"\n✅ Total unique tickers: {len(tickers_list)}")
    return tickers_list


if __name__ == "__main__":
    tickers = fetch_russell1000_tickers()
    print("\nFirst 20 tickers:", tickers[:20])
    print("Last 20 tickers:", tickers[-20:])

