"""BDS D1 almanac and RINEX 3 legacy broadcast satellite positions.

Coordinates are BDCS ECEF metres at the requested system time, not reception-
frame range coordinates. No signal-flight Sagnac or antenna offset is applied.
Almanacs use ICD table 5-15; broadcast GEO uses the ICD -5 degree rotation.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import math

MU = 3.986004418e14
OMEGA_E = 7.2921150e-5
WEEK = 604800
BDT_EPOCH = datetime(2006, 1, 1)


def wrap_week(dt):
    """ICD nearest-week interval. WNa must be checked separately if available."""
    while dt > 302400: dt -= WEEK
    while dt < -302400: dt += WEEK
    return dt


def kepler(mean_anomaly, eccentricity):
    if not 0 <= eccentricity < 1:
        raise ValueError('Elliptic orbit requires 0 <= e < 1')
    M = math.remainder(mean_anomaly, 2*math.pi)
    E = M if eccentricity < .8 else math.pi
    for _ in range(50):
        step = (E-eccentricity*math.sin(E)-M)/(1-eccentricity*math.cos(E))
        E -= step
        if abs(step) < 1e-14:
            if abs(E-eccentricity*math.sin(E)-M) > 1e-13:
                raise ArithmeticError('Kepler residual too large')
            return E
    raise ArithmeticError('Kepler solver did not converge')


def orbit_plane(x, y, inclination, ascending_node):
    c, s = math.cos(ascending_node), math.sin(ascending_node)
    ci, si = math.cos(inclination), math.sin(inclination)
    return (x*c-y*ci*s, x*s+y*ci*c, y*si)


def almanac_position(a, sow_bdt, orbit_type):
    """D1 ICD almanac algorithm, all GEO/MEO/IGSO in the same ECEF formula.

    a is the parser's parameter dictionary. A missing WNa means this result is
    conditional on the ICD nearest-week interpretation, not verified age.
    """
    if orbit_type not in ('GEO','MEO','IGSO'): raise ValueError('Unknown orbit type')
    A = a['sqrt_a_m_half']**2
    if A <= 0 or not 0 <= a['toa_s'] <= 602112:
        raise ValueError('Invalid almanac A or toa')
    tk = wrap_week(sow_bdt-a['toa_s'])
    E = kepler(a['mean_anomaly_rad']+math.sqrt(MU/A**3)*tk,a['eccentricity'])
    v = math.atan2(math.sqrt(1-a['eccentricity']**2)*math.sin(E),
                   math.cos(E)-a['eccentricity'])
    u = v+a['argument_of_perigee_rad']
    radius = A*(1-a['eccentricity']*math.cos(E))
    inc = (0 if orbit_type=='GEO' else .3*math.pi)+a['inclination_offset_rad']
    node = a['omega0_rad']+(a['omega_dot_rad_per_s']-OMEGA_E)*tk-OMEGA_E*a['toa_s']
    return orbit_plane(radius*math.cos(u),radius*math.sin(u),inc,node)


@dataclass
class BroadcastEphemeris:
    prn: int
    toc_bdt_abs: float
    af0: float
    af1: float
    af2: float
    aode: int
    crs: float
    delta_n: float
    m0: float
    cuc: float
    e: float
    cus: float
    sqrt_a: float
    toe_sow: float
    cic: float
    omega0: float
    cis: float
    i0: float
    crc: float
    omega: float
    omega_dot: float
    idot: float
    week_bdt: int
    ura: float
    health: int
    tgd1: float
    tgd2: float
    transmission_sow: float
    aodc: int
    source_file: str
    source_line: int

    @property
    def toe_bdt_abs(self): return self.week_bdt*WEEK+self.toe_sow


def read_rinex3_bds(path):
    """Read fixed-column RINEX 3.x legacy BDS DNAV records (8 lines).

    RINEX 4 and modern CNAV orbit models are deliberately rejected.
    BDS toc calendar and week fields are BDT, not GPST or UTC.
    """
    path=Path(path);lines=path.read_text(encoding='ascii').splitlines()
    version=float(lines[0][:9])
    if not 3<=version<4:raise ValueError('Only RINEX 3 navigation is supported')
    end=next(i for i,l in enumerate(lines) if 'END OF HEADER' in l)
    result=[];i=end+1
    def fields(line,start):
        return [float(line[k:k+19].replace('D','E').replace('d','e').strip() or '0')
                for k in range(start,start+76,19)]
    while i<len(lines):
        l=lines[i]
        if not l.strip():i+=1;continue
        if l[0] not in 'GRECJIS':raise ValueError(f'Unexpected record at line {i+1}')
        n=4 if l[0] in 'RS' else 8
        if i+n>len(lines):raise ValueError('Truncated navigation record')
        if l[0]=='C':
            date=l[3:23].split();dt=datetime(*map(int,date[:5]))
            toc=(dt-BDT_EPOCH).total_seconds()+float(date[5])
            af=[float(l[k:k+19].replace('D','E')) for k in (23,42,61)]
            v=[fields(lines[i+j],4) for j in range(1,8)]
            result.append(BroadcastEphemeris(
                int(l[1:3]),toc,*af,int(v[0][0]),v[0][1],v[0][2],v[0][3],
                *v[1],*v[2],*v[3],v[4][0],int(v[4][2]),
                v[5][0],int(v[5][1]),v[5][2],v[5][3],v[6][0],int(v[6][1]),str(path),i+1))
        i+=n
    return result


def broadcast_position(eph, bdt_abs, orbit_type):
    """ICD corrected Keplerian position with special broadcast GEO transform."""
    if orbit_type not in ('GEO','MEO','IGSO'): raise ValueError('Unknown orbit type')
    tk=bdt_abs-eph.toe_bdt_abs
    if abs(tk)>7200:raise ValueError('Broadcast orbit more than two hours from toe')
    A=eph.sqrt_a**2
    E=kepler(eph.m0+(math.sqrt(MU/A**3)+eph.delta_n)*tk,eph.e)
    v=math.atan2(math.sqrt(1-eph.e**2)*math.sin(E),math.cos(E)-eph.e)
    phi=v+eph.omega
    s,c=math.sin(2*phi),math.cos(2*phi)
    u=phi+eph.cus*s+eph.cuc*c
    radius=A*(1-eph.e*math.cos(E))+eph.crs*s+eph.crc*c
    inc=eph.i0+eph.idot*tk+eph.cis*s+eph.cic*c
    node=eph.omega0+eph.omega_dot*tk-OMEGA_E*eph.toe_sow
    if orbit_type!='GEO':node-=OMEGA_E*tk
    x,y,z=orbit_plane(radius*math.cos(u),radius*math.sin(u),inc,node)
    if orbit_type=='GEO':
        angle=OMEGA_E*tk;ca,sa=math.cos(angle),math.sin(angle)
        ct,st=math.cos(-math.pi/36),math.sin(-math.pi/36)
        x,y,z=x*ca+y*sa*ct+z*sa*st,-x*sa+y*ca*ct+z*ca*st,-y*st+z*ct
    return x,y,z


def select_ephemeris(ephemerides,prn,bdt_abs):
    """Healthy, already-issued record with nearest past toe, max age one hour."""
    candidates=[e for e in ephemerides if e.prn==prn and e.health==0
                and e.toc_bdt_abs<=bdt_abs and 0<=bdt_abs-e.toe_bdt_abs<=3600
                and 0<=wrap_week(bdt_abs%WEEK-e.transmission_sow)<=7200]
    if not candidates:raise LookupError(f'C{prn:02d}: no healthy, issued, in-window broadcast ephemeris')
    return min(candidates,key=lambda e:(bdt_abs-e.toe_bdt_abs,abs(bdt_abs-e.toc_bdt_abs)))
