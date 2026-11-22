"""Native GEO-MAP primitives for individually insertable forest map signs."""
KINDS = ("conifer","deciduous","clearcut","marsh","power","gas","boundary","path","shared")
NUMBER = "compartment"

def primitives(item):
    kind=item["kind"]
    if kind==NUMBER:
        # TX is the number. A1 is the native height of the sheet lettering.
        y=-item["y"]-item["h"]/2
        x=item["x"]+item["w"]/2
        fields={"TX":item["text"],"A1":f'{item["h"]*.7:.3f}'}
        return [("6900",[(y,x-item["w"]/4),(y,x+item["w"]/4)],False,"#111111",fields)]
    parts=[]
    def line(code,color,points,filled=False):
        pts=[(-item["y"]-v*item["h"]/16,item["x"]+u*item["w"]/48) for u,v in points]
        parts.append((code,pts,filled,color,{}))
    def rect(code,color,x,y,w,h):
        line(code,color,[(x,y),(x+w,y),(x+w,y+h),(x,y+h)],True)
    if kind=="conifer":
        line("1431","#24813b",[(17,14),(22,2),(27,14)])
    elif kind=="deciduous":
        line("1432","#24813b",[(22,15),(22,11),(18,10),(17,6),(19,2),(24,2),(27,6),(26,10),(22,11)])
    elif kind=="clearcut":
        rect("5200","#111111",9,4,14,8)
        line("5200","#111111",[(23,12),(39,12)])
    elif kind=="marsh":
        for x in (2,34):
            for y in (3,8,13):
                line("1461","#497842",[(x,y),(x+11,y)])
        line("2613","#3874a0",[(15,6),(19,11),(23,6),(27,11),(31,6)])
    elif kind in ("power","gas"):
        code="2364" if kind=="power" else "2613"
        if kind=="gas":
            rect("5741","#edce39",1,4,46,8)
        else:
            line(code,"#415c9b",[(1,8),(47,8)])
        for x in (13,31):
            line(code,"#26334a",[(x,4),(x+6,8),(x,12)])
    elif kind=="boundary":
        rect("5200","#ce2532",1,6,46,4)
    elif kind=="path":
        for x in (1,13,25,37):
            line("4588","#444444",[(x,8),(x+8,8)])
    elif kind=="shared":
        rect("5219","#45bbbb",1,1,46,14)
    return parts
