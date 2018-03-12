# rivers2stratigraphy GUI -- build river stratigraphy interactively
#   Stratigraphic model based on LAB models, i.e., geometric channel body is  
#   deposited in "matrix" of floodplain mud. The channel is always fixed to the 
#   basin surface and subsidence is only control on vertical stratigraphy.
#   Horizontal stratigraphy is set by 1) lateral migration (drawn from a pdf) 
#   and dampened for realism, and 2) avulsion that is set to a fixed value.
#   Default parameters are based on measurements for Piceance and Big Horn 
#   basins from Foreman et al., 2012 and Foreman, 2014
#
#   written by Andrew J. Moodie
#   amoodie@rice.edu
#   Feb 2018
#
#   TODO:
#    - control for "natural" ad default where lateral migration 
#       and Ta are a function of sediment transport (Qw)
#    - support for coloring by subsidence
#    - fix runtime warnings on startup

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.widgets as widget
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, LineCollection
import shapely.geometry as sg
import shapely.ops as so
from itertools import compress
import geom, sedtrans, utils

import time # DELETE FOR RELEASE


# model run params
dt = 50 # timestep in yrs
Bb = 2000 # width of belt

# setup params
Cf = 0.004 # friction coeff
D50 = 300*1e-6
Beta = 1.5 # exponent to avulsion function
Gamma = 1e-2 # factor for avulsion timing
Df = 0.001 # dampening factor to lateral migration rate change
dxstd = 0.5 # stdev of lateral migration dist, [m/yr]?

conR = 1.65 
cong = 9.81
conrhof = 1000
connu = 1.004e-6
    
# initial conditions
yViewInit = 100
QwInit = 1000
Qhat = geom.Qhatfun(QwInit, D50, cong) # dimensionless Qw
Rep = geom.Repfun(D50, conR, cong, connu) # particle Reynolds num
Hbar = geom.Hbarfun(Qhat, Rep) # dimensionless depth
Hnbf = geom.dimless2dimfun(Hbar, QwInit, cong) # depth
Bast = -yViewInit + Hnbf # Basin top level
Bast = 0 # Basin top level
Ccc = np.array([ (Bb / 2), (0 - (Hnbf / 2)) ]) # Channel center center
avulct = 0 # count time since last avul (for triggering)
dx = dt * (dxstd * np.random.randn()) # lateral migration per timestep [m/yr]

# setup the figure
plt.rcParams['toolbar'] = 'None'
plt.rcParams['figure.figsize'] = 8, 6
plt.ion()
fig, ax = plt.subplots()
plt.subplots_adjust(left=0.085, bottom=0.1, top=0.95, right=0.5)
ax.set_xlabel("channel belt (m)")
ax.set_ylabel("stratigraphy (m)")
plt.ylim(-yViewInit, 0.1*yViewInit)
plt.xlim(0, Bb)

# add plot elements
BastLine, = plt.plot([0, Bb*2], [Bast, Bast], 'k--') # plot basin top

# define reset functions, must operate on global vars
def slide_reset(event):
    slide_Qw.reset()
    slide_sig.reset()
    slide_Ta.reset()
    rad_col.set_active(0)
    slide_yView.reset()


def axis_reset(event):
    chanList = []
    chanListPoly = []


# add sliders
widget_color = 'lightgoldenrodyellow'

QwInit = QwInit
Qwmin = 200
Qwmax = 4000
Qwstep = 100
slide_Qw_ax = plt.axes([0.565, 0.875, 0.36, 0.05], facecolor=widget_color)
slide_Qw = utils.MinMaxSlider(slide_Qw_ax, 'water discharge (m$^3$/s)', Qwmin, Qwmax, 
valinit=QwInit, valstep=Qwstep, valfmt="%0.0f", transform=ax.transAxes)

sigInit = 2
sigmin = 0
sigmax = 5
sigstep = 0.2
slide_sig_ax = plt.axes([0.565, 0.75, 0.36, 0.05], facecolor=widget_color)
slide_sig = utils.MinMaxSlider(slide_sig_ax, 'subsidence (mm/yr)', sigmin, sigmax, 
valinit=sigInit, valstep=sigstep, valfmt="%g", transform=ax.transAxes)

TaInit = 500
Tamin = dt
Tamax = 1500
slide_Ta_ax = plt.axes([0.565, 0.625, 0.36, 0.05], facecolor=widget_color)
slide_Ta = utils.MinMaxSlider(slide_Ta_ax, 'avulsion timescale (yr)', Tamin, Tamax, 
valinit=TaInit, valstep=10, valfmt="%i", transform=ax.transAxes)
avulCmap = plt.cm.Set1(range(9))

rad_col_ax = plt.axes([0.565, 0.4, 0.225, 0.15], facecolor=widget_color)
rad_col = widget.RadioButtons(rad_col_ax, ('Deposit age', 'Water discharge', 'Subsidence rate', 'Avulsion number'))

yViewInit = yViewInit
yViewmin = 25
yViewmax = 250
slide_yView_ax = plt.axes([0.565, 0.275, 0.36, 0.05], facecolor=widget_color)
slide_yView = utils.MinMaxSlider(slide_yView_ax, 'stratigraphic view (m)', yViewmin, yViewmax, 
valinit=yViewInit, valstep=25, valfmt="%i", transform=ax.transAxes)

btn_slidereset_ax = plt.axes([0.75, 0.03, 0.2, 0.04])
btn_slidereset = widget.Button(btn_slidereset_ax, 'Reset sliders', color=widget_color, hovercolor='0.975')
btn_slidereset.on_clicked(slide_reset)

btn_axisreset_ax = plt.axes([0.75, 0.08, 0.2, 0.04])
btn_axisreset = widget.Button(btn_axisreset_ax, 'Reset stratigraphy', color=widget_color, hovercolor='0.975')
btn_axisreset.on_clicked(axis_reset)


# initialize a few more things
loopcnt = 0 # loop counter
avulcnt = 0 # avulsion timer 
avulrec = 0 # number avulsion
    
chanAct = np.zeros(1, dtype=[('coords', float, (4,2)),
                             ('sig',    float,  4),
                             ('avul',   float,  4),
                             ('Qw',     float,  4),
                             ('age',    int,    1)])
chanList = chanAct # all channels in memory
chanListPoly = []
chanColl = PatchCollection(chanListPoly)
ax.add_collection(chanColl)

chanActShp = sg.box(Ccc[0], Ccc[1], Ccc[0], Ccc[1])

col_dict = {'Water discharge': 'Qw', 
            'Avulsion number': 'avul',
            'Deposit age': 'age',
            'Subsidence rate':'sig'}

# time looping
while plt.fignum_exists(1):
    
    # get new values from sliders -- do this only if changed?
    Qw = slide_Qw.val
    sig = slide_sig.val / 1000
    Ta = slide_Ta.val
    yView = slide_yView.val
    colFlag = col_dict[rad_col.value_selected]

    # find new geom
    Qhat = geom.Qhatfun(Qw, D50, cong)
    Hbar = geom.Hbarfun(Qhat, Rep)
    Bcbar = geom.Bbarfun(Qhat, Rep)
    Sbar = geom.Sbarfun(Qhat, Rep)
    Hnbf = geom.dimless2dimfun(Hbar, Qw, cong) # new depth
    Bc = geom.dimless2dimfun(Bcbar, Qw, cong) # new width
    S = Sbar
    
    # update model configurations
    qsin = sedtrans.qsEH(D50, Cf, 
                         sedtrans.taubfun(Hnbf, S, cong, conrhof), 
                         conR, cong, conrhof)  # sedment transport rate based on new geom
    dx = (dt * dxstd * np.random.randn()) + ((1-Df)*dx) # lateral migration for dt
    Bast = Bast + (sig * dt)
    while Ccc[0] + dx > Bb-(Bc/2) or Ccc[0] + dx < 0+(Bc/2): # keep channel within belt
        dx = (dt * dxstd * np.random.randn()) + ((1-Df)*dx)
    Ccc = [Ccc[0] + dx, Bast - (Hnbf/2)] # new channel center
    
    # update plot
    if loopcnt % 10 == 0 or avulcnt == 0:
        BastLine.set_ydata([Bast, Bast])

        newCoords = geom.Ccc2coordsfun(Ccc, Bc, Hnbf)
        newActShp = sg.box(Ccc[0]-Bc/2, Ccc[1]-Hnbf/2, Ccc[0]+Bc/2, Ccc[1]+Hnbf/2)
        chanAct['coords'] = newCoords
        chanAct['sig'] = plt.cm.viridis(utils.normalizeColor(sig*1000, sigmin, sigmax))
        chanAct['avul'] = avulCmap[avulrec % 9]
        chanAct['Qw'] = plt.cm.viridis(utils.normalizeColor(Qw, Qwmin, Qwmax))
        chanAct['age'] = loopcnt

        # method 1 -- all indiv
        chanActPoly = Polygon(newCoords, facecolor='0.5', edgecolor='black')
        
        # method 2 -- unions
        # # do somethign with if dx is too large, then splice a couple more
        # # channels in between to ensure it is a single polygon?!
        # chanActShp_un = so.unary_union([chanActShp, newActShp])
        # n_split = 0 # number of times the distance has been spaced
        
        # # while chanActShp_un.type == 'MultiPolygon':
        # #     print("is multi")

        # #     n_split += 1

        # if chanActShp_un.type == 'Polygon':
        #     chanActShp = chanActShp_un
        # elif chanActShp_un.type == 'MultiPolygon':
        #     chanActPtList = geom.concave_hull(sg.mapping(chanActShp), sg.mapping(newActShp), dx)
        #     chanActShp = sg.Polygon(chanActPtList)
        # chanActPoly = Polygon(np.transpose((*[chanActShp.exterior.xy])))

        chanList = np.vstack((chanList, chanAct))
        chanListPoly.append(chanActPoly)

        chanColl.remove()
        chanColl = PatchCollection(chanListPoly)
        chanColl.set_edgecolor('0')
        if colFlag == 'Qw':
            chanColl.set_facecolor( np.vstack(chanList['Qw']) )
        elif colFlag == 'avul':
            chanColl.set_facecolor( np.vstack(chanList['avul']) )
        elif colFlag == 'age':
            ageCmap = plt.cm.viridis( utils.normalizeColor(
                chanList['age'], chanList['age'].min(), loopcnt).flatten() )
            chanColl.set_facecolor( ageCmap )
        elif colFlag == 'sig':
            chanColl.set_facecolor( np.vstack(chanList['sig']) )
        ax.add_collection(chanColl)

        # scroll the view
        ax.set_ylim(utils.new_ylims(yView, Bast))

    # avulsion handler
    avulcnt += 1 # increase since avul count
    if avulcnt > Ta: # if time since is more than Ta: due for one
        Ccc = np.hstack([np.random.uniform(Bc/2, Bb-Bc/2, 1), Ccc[1]])
        dx = 0 # reset dampening to 0 for new channel
        avulcnt = 0 # reset count
        avulrec += 1 # increment avulsion number
        chanActShp = sg.box(Ccc[0]-Bc/2, Ccc[1]-Hnbf/2, Ccc[0]+Bc/2, Ccc[1]+Hnbf/2)

    # remove outdated channels
    stratMax = Bast - yViewmax
    chanListOutdatedIdx = geom.outdatedIndex(chanList, stratMax)
    chanList = chanList[ ~chanListOutdatedIdx ]
    chanListPoly = [i for (i, v) in 
                    zip(chanListPoly, chanListOutdatedIdx) if not v]

    # draw and update counts
    plt.pause(0.000001)
    avulcnt += dt
    loopcnt += dt

