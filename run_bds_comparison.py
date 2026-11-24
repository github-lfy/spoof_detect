"""Reproduce the seven requested processing stages offline from downloaded data."""
from pathlib import Path
from datetime import datetime,timedelta
import csv,json,math,statistics,hashlib
import bds_position as b
import generate_almanac_report as audit
from fetch_reference_data import whu_web

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/position_comparison'
TYPES={16:'IGSO',19:'MEO',20:'MEO',21:'MEO',62:'GEO'}


def csv_write(name,rows):
    if not rows:return
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def rms(values):return math.sqrt(statistics.mean(x*x for x in values))


def run():
    OUT.mkdir(exist_ok=True)
    receipt=whu_web()
    report=audit.analyze()
    (OUT/'step1_decoded_almanacs.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    nav=b.read_rinex3_bds(ROOT/'reference_data/WHU_BRDC00IGS_R_20263090000_01D_MN.rnx')
    dlr=b.read_rinex3_bds(ROOT/'reference_data/WHU_BRDM00DLR_S_20263090000_01D_MN.rnx')
    groups=[g for g in report['groups'] if not g['issues']]
    epochs=sorted({(r['gps_week'],r['gps_tow_ms']) for r in report['records']})
    alm_rows=[];brdc_rows=[];comparison=[];missing=[];sow_rows=[]
    native_cache={}
    for gpsweek,towms in epochs:
        bdt_abs=(gpsweek-1356)*b.WEEK+towms/1000-14
        sow=bdt_abs%b.WEEK
        utc=datetime(1980,1,6)+timedelta(weeks=gpsweek,milliseconds=towms,seconds=-18)
        for prn in sorted(TYPES):
            try:
                e=b.select_ephemeris(nav,prn,bdt_abs)
                xyz=b.broadcast_position(e,bdt_abs,TYPES[prn]);native_cache[(prn,bdt_abs)]=(e,xyz)
                brdc_rows.append(dict(prn=prn,gps_week=gpsweek,gps_tow_ms=towms,utc=utc.isoformat(),
                    bdt_abs=bdt_abs,sow_bdt=sow,x_m=xyz[0],y_m=xyz[1],z_m=xyz[2],
                    toe_sow=e.toe_sow,toe_age_s=bdt_abs-e.toe_bdt_abs,health=e.health,
                    nav_source_line=e.source_line,aode=e.aode))
            except LookupError as err:
                missing.append(dict(prn=prn,gps_tow_ms=towms,reason=str(err),
                                    in_igs_file=any(x.prn==prn for x in nav),in_dlr_file=any(x.prn==prn for x in dlr)))
        for g in groups:
            a=g['almanac'];prn=a['prn'];xyz=b.almanac_position(a,sow,TYPES[prn])
            row=dict(group=g['id'],prn=prn,orbit_type=TYPES[prn],toa_s=a['toa_s'],
                     gps_week=gpsweek,gps_tow_ms=towms,utc=utc.isoformat(),bdt_abs=bdt_abs,
                     sow_bdt=sow,tk_s=b.wrap_week(sow-a['toa_s']),x_m=xyz[0],y_m=xyz[1],z_m=xyz[2],
                     WNa_status='unknown_nearest_week_assumption',health_status='unknown')
            alm_rows.append(row)
            if (prn,bdt_abs) not in native_cache:continue
            e,ref=native_cache[(prn,bdt_abs)];delta=[xyz[i]-ref[i] for i in range(3)]
            comparison.append(dict(group=g['id'],prn=prn,toa_s=a['toa_s'],gps_tow_ms=towms,
                utc=utc.isoformat(),sow_bdt=sow,alm_x_m=xyz[0],alm_y_m=xyz[1],alm_z_m=xyz[2],
                brdc_x_m=ref[0],brdc_y_m=ref[1],brdc_z_m=ref[2],
                dx_m=delta[0],dy_m=delta[1],dz_m=delta[2],d3_m=math.sqrt(sum(x*x for x in delta)),
                nav_toe_sow=e.toe_sow,nav_source_line=e.source_line))
    # Extra results at each captured subframe's embedded SOW, not confused with header time.
    for r in report['records']:
        if r['status']!='decoded_nonzero':continue
        a=r['almanac'];prn=a['prn'];sow=r['sow_bdt'];time=(r['gps_week']-1356)*b.WEEK+sow
        xyz=b.almanac_position(a,sow,TYPES[prn]);row=dict(source_line=r['source_line'],prn=prn,
             transmitting_prn=r['satellite_id'],subframe_sow_bdt=sow,header_sow_bdt=r['gps_tow_ms']/1000-14,
             alm_x_m=xyz[0],alm_y_m=xyz[1],alm_z_m=xyz[2],brdc_x_m=None,brdc_y_m=None,brdc_z_m=None,d3_m=None)
        try:
            eph=b.select_ephemeris(nav,prn,time);ref=b.broadcast_position(eph,time,TYPES[prn])
            row.update(brdc_x_m=ref[0],brdc_y_m=ref[1],brdc_z_m=ref[2],d3_m=math.dist(xyz,ref))
        except LookupError:pass
        sow_rows.append(row)
    summary=[]
    for g in groups:
        rows=[r for r in comparison if r['group']==g['id']]
        if not rows:continue
        d=[r['d3_m'] for r in rows]
        summary.append(dict(group=g['id'],prn=g['almanac']['prn'],toa_s=g['almanac']['toa_s'],
            N=len(rows),mean_dx_m=statistics.mean(r['dx_m'] for r in rows),mean_dy_m=statistics.mean(r['dy_m'] for r in rows),
            mean_dz_m=statistics.mean(r['dz_m'] for r in rows),rms_x_m=rms([r['dx_m'] for r in rows]),
            rms_y_m=rms([r['dy_m'] for r in rows]),rms_z_m=rms([r['dz_m'] for r in rows]),
            mean_3d_m=statistics.mean(d),rms_3d_m=rms(d),min_3d_m=min(d),max_3d_m=max(d),
            std_3d_population_m=statistics.pstdev(d)))
    # Main overall result: choose the larger toe-valued variant for each target once.
    selected={prn:max([g for g in groups if g['almanac']['prn']==prn],key=lambda g:g['almanac']['toa_s'])['id'] for prn in [19,20,21]}
    main=[r for r in comparison if selected.get(r['prn'])==r['group']]
    overall=dict(N=len(main),groups=list(selected.values()),mean_3d_m=statistics.mean(r['d3_m'] for r in main),
                 rms_3d_m=rms([r['d3_m'] for r in main]),min_3d_m=min(r['d3_m'] for r in main),
                 max_3d_m=max(r['d3_m'] for r in main))
    # Cross-center orbit agreement on matched targets, at all requested times.
    cross=[]
    for row in brdc_rows:
        try:
            e=b.select_ephemeris(dlr,row['prn'],row['bdt_abs'])
            xyz=b.broadcast_position(e,row['bdt_abs'],TYPES[row['prn']])
            cross.append(math.dist(xyz,[row['x_m'],row['y_m'],row['z_m']]))
        except LookupError:pass
    for name,rows in [('step3_almanac_positions.csv',alm_rows),('step6_broadcast_positions.csv',brdc_rows),
                      ('step6_missing_reference.csv',missing),('step7_position_differences.csv',comparison),
                      ('step7_statistics.csv',summary),('subframe_sow_positions.csv',sow_rows)]:csv_write(name,rows)
    result=dict(date_utc='2026-11-05',day_of_year=309,message_count=len(report['records']),
                unique_epochs=len(epochs),almanac_positions=len(alm_rows),broadcast_positions=len(brdc_rows),
                comparison_rows=len(comparison),nav_bds_records=len(nav),dlr_bds_records=len(dlr),
                missing_target_prns=[16,62],source_sha256=report['source_sha256'],download_receipt=receipt,
                statistics=summary,overall_preferred_variant=overall,
                cross_center=dict(N=len(cross),max_3d_m=max(cross),rms_3d_m=rms(cross)),
                first_utc=alm_rows[0]['utc'],last_utc=alm_rows[-1]['utc'])
    (OUT/'comparison_summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return result


if __name__=='__main__':run()
