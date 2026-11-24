"""Independent RTKLIB parser/propagator and numerical invariant checks."""
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import pyrtklib as r
import bds_position as b
import bds_rawsubframe_almanac as raw
import generate_almanac_report as audit


def independent_almanac(a,t,kind):
    # Independent bisection solution and matrix rotations (not production helper).
    A=a['semi_major_axis_m'];tk=(t-a['toa_s']+302400)%604800-302400
    M=(a['mean_anomaly_rad']+math.sqrt(3.986004418e14/A**3)*tk+math.pi)%(2*math.pi)-math.pi
    low,high=-math.pi,math.pi
    for _ in range(100):
        E=(low+high)/2
        if E-a['eccentricity']*math.sin(E)<M:low=E
        else:high=E
    E=(low+high)/2
    planar=np.array([A*(math.cos(E)-a['eccentricity']),A*math.sqrt(1-a['eccentricity']**2)*math.sin(E),0])
    def rz(x):return np.array([[math.cos(x),-math.sin(x),0],[math.sin(x),math.cos(x),0],[0,0,1]])
    inc=(0 if kind=='GEO' else .3*math.pi)+a['inclination_offset_rad']
    rx=np.array([[1,0,0],[0,math.cos(inc),-math.sin(inc)],[0,math.sin(inc),math.cos(inc)]])
    node=a['omega0_rad']+(a['omega_dot_rad_per_s']-7.292115e-5)*tk-7.292115e-5*a['toa_s']
    return rz(node)@rx@rz(a['argument_of_perigee_rad'])@planar


def validate(navpath, report):
    tests=[]
    ephs=b.read_rinex3_bds(navpath)
    obs,nav,sta=r.obs_t(),r.nav_t(),r.sta_t()
    assert r.readrnx(str(navpath),1,'',obs,nav,sta)==1
    native={}
    for i in range(nav.n):
        e=nav.eph[i]
        for prn in range(1,64):
            if e.sat==r.satno(r.SYS_CMP,prn):
                native[(prn,e.week,e.toes)]=e;break
    assert len(ephs)==len(native)
    field_map={'m0':'M0','sqrt_a':None,'e':'e','omega0':'OMG0','omega':'omg',
               'omega_dot':'OMGd','idot':'idot','i0':'i0','crs':'crs','crc':'crc',
               'cus':'cus','cuc':'cuc','cis':'cis','cic':'cic','delta_n':'deln'}
    differences=[];fields=0
    for e in ephs:
        n=native[(e.prn,e.week_bdt,e.toe_sow)]
        for k,v in field_map.items():
            expected=math.sqrt(n.A) if v is None else getattr(n,v)
            assert abs(getattr(e,k)-expected)<1e-9
            fields+=1
        for offset in [0,600,2700,3599]:
            t=e.toe_bdt_abs+offset
            xyz=b.broadcast_position(e,t,'GEO' if e.prn<=5 or e.prn>=59 else 'MEO')
            out,clk,var=r.Arr1Ddouble(3),r.Arr1Ddouble(1),r.Arr1Ddouble(1)
            r.eph2pos(r.bdt2gpst(r.bdt2time(e.week_bdt,e.toe_sow+offset)),n,out,clk,var)
            differences.append(float(np.linalg.norm(np.array(xyz)-[out[i] for i in range(3)])))
    max_native=max(differences)
    assert max_native<.001
    tests.append(dict(name='Independent native RTKLIB RINEX parser and broadcast positions',
                      ephemerides=len(ephs),fields=fields,positions=len(differences),max_difference_m=max_native,
                      tolerance_m=.001,passed=True,package='pyrtklib==0.2.7'))
    ds=[];bitchecks=0
    for g in report['groups']:
        m,w=raw.parse_sentence(g['representative_sentence']);bits=raw.words_to_bits(w)
        data=int(bits+'0000',2).to_bytes(38,'big')
        arr=getattr(r,'Arr1Dunsigned char')(38)
        for i,v in enumerate(data):arr[i]=v
        for tr in g['trace']:
            v=0
            for start,width in tr['icd_parts']:v=(v<<width)|r.getbitu(arr,start-1,width)
            if tr['signed'] and v>>(len(tr['binary'])-1):v-=1<<len(tr['binary'])
            assert v==tr['integer'];bitchecks+=1
        if g['issues']:continue
        a=g['almanac'];kind='GEO' if a['prn']>=59 else 'IGSO' if a['prn']==16 else 'MEO'
        for t in [0,1,604799,a['toa_s'],a['toa_s']+302399,359035]:
            ds.append(float(np.linalg.norm(np.array(b.almanac_position(a,t,kind))-independent_almanac(a,t,kind))))
    assert max(ds)<1e-5
    tests.append(dict(name='Native RTKLIB unsigned bit extraction and signed field reconstruction',
                      fields=bitchecks,passed=True))
    tests.append(dict(name='Independent bisection and rotation-matrix almanac solution including week boundaries',
                      cases=len(ds),max_difference_m=max(ds),tolerance_m=1e-5,passed=True))
    # Circular equatorial reference at t=toa=0 is [A,0,0]; quarter orbit rotates in ECEF.
    a=report['groups'][0]['almanac'].copy()
    a.update(eccentricity=0,toa_s=0,mean_anomaly_rad=0,argument_of_perigee_rad=0,
             omega0_rad=0,omega_dot_rad_per_s=0,inclination_offset_rad=0)
    A=a['sqrt_a_m_half']**2
    assert np.linalg.norm(np.array(b.almanac_position(a,0,'GEO'))-[A,0,0])<1e-8
    for ecc in [0,.01,.062499,.9,.99]:
        for M in [-10,-math.pi,-.01,0,.01,math.pi,10]:
            E=b.kepler(M,ecc)
            assert abs(E-ecc*math.sin(E)-math.remainder(M,2*math.pi))<1e-13
    assert b.wrap_week(604799)==-1 and b.wrap_week(-604799)==1
    bad=report['records'][0]['sentence'];bad=bad[:-1]+('0' if bad[-1]!='0' else '1')
    try:raw.parse_sentence(bad)
    except ValueError:pass
    else:raise AssertionError('CRC corruption accepted')
    tests.append(dict(name='Analytic circular reference, Kepler residual, week crossover and corrupted CRC',passed=True))
    return tests


if __name__=='__main__':
    report=audit.analyze()
    tests=validate(ROOT/'reference_data/WHU_BRDC00IGS_R_20263090000_01D_MN.rnx',report)
    target=ROOT/'output/position_comparison';target.mkdir(exist_ok=True)
    (target/'validation_results.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
    print(json.dumps(tests,indent=2))
