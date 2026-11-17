"""No GUI needed: inspect metadata and verify map checksums."""
import json
import sys
from .geomap import GeoMap, library_layers, library_symbols, library_colors

def main():
    if len(sys.argv)<2:
        print('Usage: python -m geostudio.inspect FILE.MAP [LIBRARY.LAY] [LIBRARY.SYM] [LIBRARY.CDF]')
        raise SystemExit(2)
    doc=GeoMap.open(sys.argv[1]); s=doc.summary()
    for fname in sys.argv[2:]:
        suffix=fname.lower().split('.')[-1]
        if suffix=='lay':
            groups,codes=library_layers(fname);s['library_layers']={'groups':len(groups),'codes':len(codes),'names':groups}
        elif suffix=='sym':s['library_symbol_count']=len(library_symbols(fname))
        elif suffix=='cdf':s['library_color_count']=len(library_colors(fname))
    print(json.dumps(s,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
