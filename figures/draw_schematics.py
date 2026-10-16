"""Vector drawing primitives; copied into each independent project generator."""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle, FancyArrowPatch

plt.rcParams.update({'font.family':'STIXGeneral', 'mathtext.fontset':'stix',
                     'font.size':9, 'pdf.fonttype':42, 'ps.fonttype':42,
                     'text.usetex':False, 'axes.unicode_minus':False})
CM = 1 / 2.54

class Drawing:
    def __init__(self, bounds):
        x0,y0,x1,y1 = bounds
        self.fig = plt.figure(figsize=((x1-x0)*CM,(y1-y0)*CM))
        self.ax = self.fig.add_axes([0,0,1,1], xlim=(x0,x1), ylim=(y0,y1))
        self.ax.set_aspect('equal'); self.ax.axis('off')
        self.nodes = {}
        self.labels = []

    def text(self,x,y,label,size=9,ha='center',va='center'):
        artist=self.ax.text(x,y,label,fontsize=size,ha=ha,va=va,
                            linespacing=1.15,clip_on=False,zorder=4)
        self.labels.append([artist,None])
        return artist

    def box(self,name,x,y,w,h,label,dashed=False,shape='rect',size=9):
        style = {'edgecolor':'black','facecolor':'white','linewidth':.55,
                 'linestyle':(0,(4,3)) if dashed else 'solid', 'zorder':2}
        if shape == 'diamond':
            obj = Polygon([(x-w/2,y),(x,y+h/2),(x+w/2,y),(x,y-h/2)],**style)
        elif shape == 'circle': obj = Circle((x,y),w/2,**style)
        else: obj = Rectangle((x-w/2,y-h/2),w,h,**style)
        self.ax.add_patch(obj); self.text(x,y,label,size)
        self.labels[-1][1]=(x-w/2,y-h/2,x+w/2,y+h/2)
        self.nodes[name] = (x,y,w,h,shape)

    def point(self,name,side):
        x,y,w,h,_ = self.nodes[name]
        return {'n':(x,y+h/2),'s':(x,y-h/2),'e':(x+w/2,y),
                'w':(x-w/2,y),'nw':(x-w/2,y+h/2),
                'ne':(x+w/2,y+h/2),'c':(x,y)}[side]

    def line(self,points,dashed=False):
        xs,ys=zip(*points)
        self.ax.plot(xs,ys,color='black',linewidth=.55,
                     linestyle=(0,(4,3)) if dashed else 'solid',zorder=1)

    def arrow(self,p,q,dashed=False,via=()):
        points=[p,*via,q]
        if via:self.line(points[:-1],dashed)
        self.ax.add_patch(FancyArrowPatch(points[-2],points[-1],
                         arrowstyle='-|>',mutation_scale=7.5,linewidth=.55,
                         color='black',shrinkA=0,shrinkB=0,
                         linestyle=(0,(4,3)) if dashed else 'solid',zorder=1))

    def edge(self,a,b,sa='s',sb='n',**kwargs):
        self.arrow(self.point(a,sa),self.point(b,sb),**kwargs)

    def frame(self,x,y,w,h):
        self.ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor='black',
                                   linewidth=.55,linestyle=(0,(4,3)),zorder=0))

    def save(self,out,name):
        # Fixed physical canvas: do not enlarge or rasterize the scientific figure.
        self.fig.canvas.draw()
        renderer=self.fig.canvas.get_renderer()
        x0,x1=self.ax.get_xlim();y0,y1=self.ax.get_ylim()
        for artist,node in self.labels:
            b=artist.get_window_extent(renderer).transformed(self.ax.transData.inverted())
            if b.x0<x0-.02 or b.x1>x1+.02 or b.y0<y0-.02 or b.y1>y1+.02:
                raise ValueError(name+': clipped label '+repr(artist.get_text()))
            if node and (b.x0<node[0]-.02 or b.x1>node[2]+.02 or b.y0<node[1]-.02 or b.y1>node[3]+.02):
                raise ValueError(name+': label exceeds node '+repr(artist.get_text()))
        self.fig.savefig(out/(name+'.pdf'),format='pdf',
                         metadata={'Creator':'Python Matplotlib','Producer':None,
                                   'CreationDate':None,'ModDate':None})
        plt.close(self.fig)






def protocol(out):
    d=Drawing((-.3,-2.35,10.2,3.2))
    d.box('tier0',1.7,1.6,3.7,.9,'tier 0: oldest prefix $P$')
    d.box('tier1',7.9,1.6,3.7,.9,'tier 1: free reserve')
    d.arrow(d.point('tier0','n'),d.point('tier1','n'),via=[(1.7,2.65),(7.9,2.65)])
    d.text(4.8,2.98,'retained bytes $L(P)$')
    for name,x in [('copy',.9),('flush',3.3),('commit',5.7),('reclaim',8.1)]:
        d.box(name,x,.15,1.85,.65,name)
    for a,b in [('copy','flush'),('flush','commit'),('commit','reclaim')]:d.edge(a,b,'e','w')
    d.text(3.3,-.65,'new payload\ndurable',size=8.5)
    d.text(5.7,-.8,'atomic\npointer-set\ncommit',size=8.5)
    d.text(8.1,-.65,'old prefix\nreusable',size=8.5)
    d.line([(.05,-1.4),(.05,-1.52),(5.6,-1.52),(5.6,-1.4)])
    d.line([(5.8,-1.4),(5.8,-1.52),(9.5,-1.52),(9.5,-1.4)])
    d.text(2.8,-1.96,'old copy selected before commit',size=8.5)
    d.text(7.65,-1.96,'new copy selected after commit',size=8.5)
    d.save(out,'protocol')

def witness(out):
    d=Drawing((-2.5,-1.6,8.4,1.55))
    d.text(-.7,.9,'optimal',ha='right',size=8.5)
    d.text(-.7,-.15,'fragmented',ha='right',size=8.5)
    for name,x,y,label,colour in [
            ('o1',.4,.9,'$1:2$','.8'),('o0',2.1,.9,'$0:2$','.94'),
            ('f0',.2,-.15,'$0:1$','.94'),('f1',1.3,-.15,'$1:1$','.8'),
            ('f2',2.4,-.15,'$0:1$','.94'),('f3',3.5,-.15,'$1:1$','.8')]:
        d.box(name,x,y,.85,.62,label,size=8.5)
        d.ax.patches[-1].set_facecolor(colour)
    d.text(4.,.9,r'$2(q+\mu)=10$',ha='left',size=8.5)
    d.text(4.3,-.15,r'$4(q+\mu)=20$',ha='left',size=8.5)
    d.text(3.,-1.15,r'$q=4$, $\mu=1$; four unit-live segments; both schedules legal',size=8.5)
    d.save(out,'cost-witness')

def main():
    p=argparse.ArgumentParser(description='Direct vector recovery order and exact batching witness.')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    protocol(a.out);witness(a.out)
if __name__=='__main__':main()
