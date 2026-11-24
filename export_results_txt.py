"""Export existing audited results to UTF-8 TXT without recomputing positions."""
from pathlib import Path
import csv
import json
import math

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'output' / 'position_comparison'
OUT = SOURCE / 'txt'


def read_csv(name):
    with (SOURCE / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write(name, lines):
    path = OUT / name
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return path


def export():
    OUT.mkdir(exist_ok=True)
    audit = json.loads((SOURCE / 'step1_decoded_almanacs.json').read_text(encoding='utf-8'))
    summary = json.loads((SOURCE / 'comparison_summary.json').read_text(encoding='utf-8'))
    groups = sorted(audit['groups'], key=lambda g: (g['almanac']['prn'], -g['almanac']['toa_s'], g['id']))
    labels = [
        ('sqrt_a_m_half', 'sqrt(A)', 'm^0.5'),
        ('semi_major_axis_m', 'A 半长轴', 'm'),
        ('eccentricity', 'e 偏心率', '无量纲'),
        ('inclination_offset_rad', 'delta_i 倾角改正量', 'rad'),
        ('inclination_offset_semicircles', 'delta_i 倾角改正量', '半周'),
        ('omega0_rad', 'Omega0 升交点经度', 'rad'),
        ('omega0_semicircles', 'Omega0 升交点经度', '半周'),
        ('omega_dot_rad_per_s', 'Omega_dot 升交点经度变化率', 'rad/s'),
        ('omega_dot_semicircles_per_s', 'Omega_dot 升交点经度变化率', '半周/s'),
        ('argument_of_perigee_rad', 'omega 近地点幅角', 'rad'),
        ('argument_of_perigee_semicircles', 'omega 近地点幅角', '半周'),
        ('mean_anomaly_rad', 'M0 参考时刻平近点角', 'rad'),
        ('mean_anomaly_semicircles', 'M0 参考时刻平近点角', '半周'),
        ('toa_s', 'toa 历书参考周内秒', 'BDT s'),
        ('clock_a0_s', 'a0 卫星钟差', 's'),
        ('clock_a1_s_per_s', 'a1 卫星钟漂', 's/s'),
    ]
    lines = [
        'UT986 BDSRAWSUBFRAME 北斗历书参数',
        '数据日期：2026-11-05；原始文件：bdsrawsubfram_message.txt',
        '保留每颗目标卫星的全部参数版本；转播卫星与历书目标卫星不是同一概念。',
        '共有16组解析候选：8组非零且通过范围检查，覆盖C16、C19、C20、C21、C62。',
        '全零或异常候选单列，未用于位置计算；C17、C18、C63没有通过检查的历书版本。',
        'WNa历书周号及健康状态均未获得。当前BDT周1087不能作为已知的历书周号。',
        'delta_i为参考倾角的改正量，不是完整倾角；MEO/IGSO参考倾角为0.30*pi，GEO为0。',
        '数值保留JSON中的双精度表示；显示位数不代表物理精度。',
        '源文件SHA-256：' + audit['source_sha256'], '',
    ]
    for g in groups:
        a = g['almanac']
        lines += ['=' * 80, f'目标卫星 C{a["prn"]:02d}    参数组 {g["id"]}',
                  '状态：' + ('非零且通过范围检查，WNa及健康状态未知' if not g['issues'] else '不可用或异常候选，不用于位置计算'),
                  '诊断：' + (', '.join(g['issues']) if g['issues'] else '无范围检查异常'),
                  f'子帧={a["subframe_id"]}    页号={a["page_number"]}',
                  'AmEpID：' + (str(a['expanded_almanac_id']) if a['expanded_almanac_id'] is not None else '由同源先前子帧4确认=3'),
                  'AmID：' + (str(a['time_sharing_id']) if a['time_sharing_id'] is not None else '不适用'),
                  '转播卫星：' + ', '.join(f'C{x:02d}' for x in g['transmitting_satellites']),
                  '源文件行号：' + ', '.join(map(str, g['source_lines'])),
                  '转播记录数：' + str(g['count']), '', '参数\t数值\t单位']
        for key, label, unit in labels:
            lines.append(f'{label}\t{a[key]}\t{unit}')
        lines += ['', '字段追溯：参数\tICD位段(1基)\t原始位串\t无符号整数\t补码后整数\t比例因子\t单位']
        for t in g['trace']:
            parts = ','.join(f'{start}-{start + width - 1}' for start, width in t['icd_parts'])
            lines.append('\t'.join(map(str, [t['parameter'], parts, t['binary'], t['unsigned_integer'],
                                               t['integer'], t['scale'], t['unit']])))
        lines += ['', '原始消息：', g['representative_sentence'], '']
    params = write('BDS_各卫星历书参数.txt', lines)

    almanac = read_csv('step3_almanac_positions.csv')
    differences = read_csv('step7_position_differences.csv')
    diff_index = {(r['group'], r['gps_tow_ms']): r for r in differences}
    combined = [
        '北斗历书位置 广播星历位置及同一时刻偏差',
        '数据日期：2026-11-05；坐标系：BDCS地固坐标；所有XYZ及偏差单位：米。',
        '目标时间采用消息头GPST，减14秒转BDT，减18秒转本日期UTC。',
        '该时间比消息内导航子帧SOW早晚关系为：消息头BDT = 子帧SOW + 7秒。',
        '差值定义：dX=X历书-X广播，dY及dZ同理，d3=sqrt(dX^2+dY^2+dZ^2)。',
        '8组历书在29个消息头时刻，共232行；其中174行有广播星历可比较。',
        'C16、C62在武大同日IGS、DLR RINEX3及DLR RINEX4中无星历记录，广播位置及偏差记为NA。',
        'C16按IGSO、C62按GEO为条件计算；WNa与健康状态未知，历书采用ICD最近半周归算。',
        '同一卫星不同toa的版本分别保存。保留原CSV数值，不额外舍入。',
        '以下为Tab分隔文本，可用文本编辑器查看，或导入表格软件。', '',
    ]
    headers = ['目标卫星', '参数组', 'toa_BDT_s', 'UTC', 'GPS周', 'GPS周内毫秒',
               'BDT周内秒', '历书传播tk_s', '历书X_m', '历书Y_m', '历书Z_m',
               '广播X_m', '广播Y_m', '广播Z_m', 'dX_m', 'dY_m', 'dZ_m', 'd3_m', '状态']
    combined.append('\t'.join(headers))
    for row in sorted(almanac, key=lambda r: (int(r['prn']), r['group'], float(r['gps_tow_ms']))):
        d = diff_index.get((row['group'], row['gps_tow_ms']))
        vals = [f'C{int(row["prn"]):02d}', row['group'], row['toa_s'], row['utc'], row['gps_week'],
                row['gps_tow_ms'], row['sow_bdt'], row['tk_s'], row['x_m'], row['y_m'], row['z_m']]
        vals += ([d[k] for k in ['brdc_x_m', 'brdc_y_m', 'brdc_z_m', 'dx_m', 'dy_m', 'dz_m', 'd3_m']]
                 if d else ['NA'] * 7)
        vals.append('可比较_历书周号及健康未知' if d else '缺少目标广播星历_仅有条件历书位置')
        combined.append('\t'.join(vals))
    positions = write('BDS_历书位置_广播星历位置_位置偏差.txt', combined)

    stats = read_csv('step7_statistics.csv')
    stat_lines = ['北斗历书与广播星历位置偏差统计',
                  '单位：米；每组29个不同消息头时刻；版本分别统计，重复转播消息不重复计权。',
                  'RMS为均方根；std_3d_population_m为三维差的总体标准差。', '',
                  '\t'.join(stats[0].keys())]
    stat_lines += ['\t'.join(row.values()) for row in stats]
    stat_lines += ['', '主版本整体统计（各卫星选择toa=94208秒一次，不按误差大小选版本）：']
    stat_lines += [f'{k}\t{v}' for k, v in summary['overall_preferred_variant'].items()]
    stats_path = write('BDS_位置偏差统计.txt', stat_lines)

    print(json.dumps(dict(files=[str(params), str(positions), str(stats_path)],
                          parameter_groups=len(groups), position_rows=len(almanac),
                          matched_rows=len(differences), unavailable_reference_rows=len(almanac)-len(differences)),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    export()
