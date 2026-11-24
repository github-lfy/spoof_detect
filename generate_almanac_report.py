"""Audit a UT986 text capture and create reproducible PDF/HTML/JSON/CSV reports."""
import csv
import hashlib
import html
import json
import math
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import bds_rawsubframe_almanac as p

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
SOURCE = ROOT / 'bdsrawsubfram_message.txt'
LAYOUT = [
    ('sqrt_a', [(51, 2), (61, 22)], False, -11, 'm^0.5'),
    ('a1', [(91, 11)], True, -38, 's/s'),
    ('a0', [(102, 11)], True, -20, 's'),
    ('omega0', [(121, 22), (151, 2)], True, -23, '半周'),
    ('e', [(153, 17)], False, -21, '1'),
    ('delta_i', [(170, 3), (181, 13)], True, -19, '半周'),
    ('toa', [(194, 8)], False, 12, 's'),
    ('omega_dot', [(202, 1), (211, 16)], True, -38, '半周/s'),
    ('omega', [(227, 6), (241, 18)], True, -23, '半周'),
    ('m0', [(259, 4), (271, 20)], True, -23, '半周'),
]
SOURCES = [
    ('和芯星通 GNSS 授时产品协议手册 CH R2.0，正文 87-88、140-143 页',
     'https://www.unicorecomm.com/assets/upload/file/GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf'),
    ('北斗 B1I SIS ICD v3.0：D1 图 5-11-1、5-11-6；扩展历书 AmEpID / AmID 定义',
     'https://en.beidou.gov.cn/SYSTEMS/ICD/201902/P020190227702348791891.pdf'),
    ('GNSS-SDR 原始定义：Beidou_DNAV.h；用于复核 D1 历书位段、比例因子和标识',
     'https://github.com/gnss-sdr/gnss-sdr/blob/main/src/core/system_parameters/Beidou_DNAV.h'),
]


def trace(bits, words):
    result = []
    for name, parts, signed, power, unit in LAYOUT:
        binary = ''.join(bits[start-1:start-1+length] for start, length in parts)
        integer = p.raw_parts(bits, parts, signed)
        result.append(dict(parameter=name, icd_parts=parts, binary=binary,
                           unsigned_integer=int(binary, 2), signed=signed,
                           integer=integer, scale=f'2^{power}', unit=unit,
                           scaled_value=integer * 2.0**power,
                           data_words=sorted({(start-1)//30 for start, _ in parts})))
    return result


def analyze():
    data = SOURCE.read_bytes()
    records, errors, groups, ctx = [], [], {}, {}
    for line_no, line in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        # Exclude conversational mentions and extract only complete captured logs.
        match = re.search(r'#BDSRAWSUBFRAMEA?,[^\r\n]*\*[0-9a-fA-F]{8}', line)
        if not match:
            continue
        sentence = match.group()
        try:
            m, words = p.parse_sentence(sentence)
            bits = p.words_to_bits(words)
            sf = p.unsigned(bits, 16, 3)
            if p.unsigned(bits, 1, 11) != 0x712:
                raise ValueError('BDS preamble mismatch')
            if sf != m['subframe_id']:
                raise ValueError('FraID mismatch')
            sow = p.joined_unsigned(bits, [(19, 8), (31, 12)])
            if sow >= 604800:
                raise ValueError('SOW out of range')
            page = p.unsigned(bits, 44, 7) if sf in (4, 5) else None
            sv = m['satellite_id']
            if sf == 4 and 1 <= page <= 24:
                ctx[sv] = (p.unsigned(bits, 291, 2), sow)
            c = ctx.get(sv)
            context = c[0] if c and 0 <= (sow-c[1]) % 604800 <= 30 else None
            a = p.decode_d1_almanac(m, words, context)
            r = dict(source_line=line_no, sentence=sentence, **m,
                     sow_bdt=sow, page=page,
                     header_minus_sow_s=m['gps_tow_ms']/1000-14-sow,
                     data_words_hex=[f'{x:08x}' for x in words],
                     information_words=[words[0] >> 4]+[x & 0x3fffff for x in words[1:]],
                     status='other_subframe')
            if sf == 1:
                r['broadcast_bdt_week'] = p.unsigned(bits, 61, 13)
            if a:
                d = asdict(a)
                r['almanac'] = d
                issues = []
                if not any(a.raw.values()):
                    issues.append('all_zero_unavailable')
                if a.sqrt_a_m_half == 0 and 'all_zero_unavailable' not in issues:
                    issues.append('zero_semi_major_axis')
                if not 0 <= a.toa_s <= 602112:
                    issues.append('toa_out_of_week')
                # An engineering consistency screen, not an ICD validity flag.
                if a.sqrt_a_m_half and not (2.5e7 <= a.semi_major_axis_m <= 4.5e7):
                    issues.append('orbit_size_outside_bds_expected_band')
                r['issues'] = issues
                r['status'] = 'candidate_with_issues' if issues else 'decoded_nonzero'
                key = (a.prn, a.expanded_almanac_id, a.time_sharing_id,
                       tuple(sorted(a.raw.items())))
                if key not in groups:
                    groups[key] = dict(almanac=d, issues=issues, status=r['status'],
                                       source_lines=[], transmitting_satellites=[],
                                       representative_sentence=sentence,
                                       data_words_hex=r['data_words_hex'],
                                       trace=trace(bits, words))
                g = groups[key]
                g['source_lines'].append(line_no)
                if sv not in g['transmitting_satellites']:
                    g['transmitting_satellites'].append(sv)
            elif sf == 5 and 11 <= page <= 23:
                amid = p.unsigned(bits, 291, 2)
                r.update(amid=amid, amepid_context=context)
                r['status'] = ('reserved_expanded_page' if context == 3 and
                               (amid == 0 or (amid == 3 and page >= 18)) else
                               'expanded_not_enabled_or_context_missing')
            records.append(r)
        except (ValueError, UnicodeError) as exc:
            errors.append(dict(source_line=line_no, error=str(exc)))
    groups = list(groups.values())
    for i, g in enumerate(groups, 1):
        g['id'] = f'G{i:02d}'
        g['count'] = len(g['source_lines'])
    good = [g for g in groups if not g['issues']]
    return dict(source=str(SOURCE), source_sha256=hashlib.sha256(data).hexdigest(),
                generated_date='2026-11-24', records=records, errors=errors,
                groups=groups, good_group_ids=[g['id'] for g in good],
                counts=dict(Counter(r['status'] for r in records)), sources=SOURCES)


def save_data(report):
    OUT.mkdir(exist_ok=True)
    (OUT/'UT986_almanac_results.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (OUT/'UT986_almanac_parameters.csv').open('w', newline='', encoding='utf-8-sig') as f:
        keys = ['group_id', 'count', 'source_lines', 'transmitting_satellites', 'status', 'issues']
        keys += list(report['groups'][0]['almanac'].keys())[:-1]
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for g in report['groups']:
            writer.writerow(dict(group_id=g['id'], count=g['count'],
                                 source_lines=';'.join(map(str,g['source_lines'])),
                                 transmitting_satellites=';'.join(map(str,g['transmitting_satellites'])),
                                 status=g['status'], issues=';'.join(g['issues']),
                                 **{k:v for k,v in g['almanac'].items() if k!='raw'}))
    with (OUT/'UT986_message_audit.csv').open('w', newline='', encoding='utf-8-sig') as f:
        keys = ['source_line','satellite_id','subframe_id','page','sow_bdt',
                'gps_week','gps_tow_ms','crc_valid','status','header_minus_sow_s']
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader();writer.writerows(report['records'])


def sections(report):
    good = [g for g in report['groups'] if not g['issues']]
    records = report['records']
    pages = sorted({r['page'] for r in records if r['page'] is not None})
    utc = lambda r: datetime(1980,1,6)+timedelta(weeks=r['gps_week'],milliseconds=r['gps_tow_ms'])-timedelta(seconds=18)
    summary = [
        ('p', f'共提取 {len(records)} 条完整消息，ASCII CRC32 全部通过；解析错误 {len(report["errors"])} 条。'
         f'采样时间为 {utc(records[0]):%Y-%m-%d %H:%M:%S} 至 {utc(records[-1]):%H:%M:%S} UTC，跨度 168 秒。'),
        ('p', f'可报告的非零历书共有 {len(good)} 组，覆盖 C16、C19、C20、C21、C62 五颗目标卫星。'
         '其中 C19、C20、C21 各有两个 toa 版本，逐组保留。C17、C18 为全零页；C63 候选存在全零、超周时间和轨道尺度异常。'),
        ('p', '“可报告”仅表示字段可解且通过本报告的范围检查，不表示历书健康或仍在有效期内。'
         '本段日志没有子帧 5 页 7、8、24，因此缺少历书周 WNa 和相应健康信息，不能给出完整历书历元或认证轨道精度。'),
        ('table', ['组','目标','toa / s','sqrt(A) / m^0.5','e','条数'],
         [[g['id'],f'C{g["almanac"]["prn"]:02d}',str(g['almanac']['toa_s']),
           f'{g["almanac"]["sqrt_a_m_half"]:.9f}',f'{g["almanac"]["eccentricity"]:.10f}',str(g['count'])] for g in good]),
        ('p', 'C19-C21 的主版本分别由六颗卫星转播，toa=94208 s；C09 转播另一个版本，toa=86016 s。'
         '转播卫星号与历书目标卫星号不同，不应混用；不同参考时刻的角参数也不能直接视为冲突。'),
        ('p', '原文件包含历史对话和接收日志。本报告只提取完整 #BDSRAWSUBFRAME...*CRC 行，'
         '不采用历史对话里的结果。原始文件未修改；所有源行号均为该文件的一基行号。'),
        ('p', '源文件 SHA-256：'+report['source_sha256']),
    ]
    result = [('解析结论与数据范围', summary)]
    rowspec = [
        ('sqrt(A) / m^0.5','sqrt_a_m_half','fixed'),('A / m','semi_major_axis_m','fixed'),
        ('e','eccentricity','fixed'),('delta_i / rad','inclination_offset_rad','fixed'),
        ('Omega0 / rad','omega0_rad','fixed'),('Omega_dot / rad/s','omega_dot_rad_per_s','sci'),
        ('omega / rad','argument_of_perigee_rad','fixed'),('M0 / rad','mean_anomaly_rad','fixed'),
        ('toa / s','toa_s','int'),('a0 / s','clock_a0_s','sci'),('a1 / (s/s)','clock_a1_s_per_s','sci')]
    for start in range(0,len(good),4):
        gs=good[start:start+4]
        rows=[]
        for label,key,fmt in rowspec:
            rows.append([label]+[(str(g['almanac'][key]) if fmt=='int' else
                         f'{g["almanac"][key]:.10e}' if fmt=='sci' else
                         f'{g["almanac"][key]:.10f}') for g in gs])
        items=[('p','角参数在下表中统一使用弧度；半周值保存在 JSON / CSV 中。'
                'delta_i 是轨道参考倾角的改正量，不是完整倾角 i。WNa 与健康状态均为未获得。'),
               ('table',['参数']+[f'{g["id"]} / C{g["almanac"]["prn"]:02d}' for g in gs],rows)]
        for g in gs:
            a=g['almanac'];items.append(('p',f'{g["id"]}：子帧 {a["subframe_id"]} / 页 {a["page_number"]}；'
                f'AmEpID={a["expanded_almanac_id"] if a["expanded_almanac_id"] is not None else "由此前同源子帧4确认11"}；'
                f'AmID={a["time_sharing_id"]}；转播卫星 '+', '.join(f'C{x:02d}' for x in g['transmitting_satellites'])+
                '；源行 '+', '.join(map(str,g['source_lines']))+'。'))
        result.append((f'非零历书参数 / {start//4+1}',items))
    anomalies=[g for g in report['groups'] if g['issues']]
    items=[('p','以下数据保留在机器可读结果中，但不作为可用轨道参数。CRC 通过说明日志传输完整，'
            '不能证明星上广播参数具有物理意义。C63 的非零候选没有做单比特修复或猜测性修正。'),
           ('table',['组 / 目标','转播卫星','sqrt(A)','toa/s','原因'],
            [[g['id']+f' / C{g["almanac"]["prn"]:02d}',
              ','.join(map(str,g['transmitting_satellites'])),
              f'{g["almanac"]["sqrt_a_m_half"]:.6f}',str(g['almanac']['toa_s']),
              '全零，无可用轨道' if 'all_zero_unavailable' in g['issues'] else
              'toa 超出 602112 s' if 'toa_out_of_week' in g['issues'] else
              'A 超出工程检查范围'] for g in anomalies]),
           ('p','C63 / C14 转播候选：toa=905216 s，超过一周，排除。C63 / C39 转播候选：'
            'A=65539112.517 m，与本报告采用的北斗轨道尺度检查区间 2.5e7-4.5e7 m 不符，暂不使用。'
            '此区间是工程筛查条件，不是 ICD 健康标志，也不能代替外部轨道比对。'),
           ('p','扩展页必须同时满足同一转播卫星的 AmEpID=11 与当前页有效 AmID。'
            '本段中 AmID=11 时，页 16 对应 C62，页 17 对应 C63；页 18-21 为保留页，不能把其中的重复填充值解成轨道。'
            'C09 的 AmEpID=01，未启用扩展页，相关子帧5不作扩展历书解析。'),
           ('p','采样只覆盖页 16-21，没有覆盖全套历书。若需完整结果，应继续采集至少一个 D1 大帧（12 分钟），'
            '并确保包含子帧5页8的 WNa、toa 和健康页，以及相关扩展标识。完整周可由 WNa 结合已知当前 BDT 周消歧，'
            '但本报告不把当前周1087直接填为历书周。')]
    result.append(('异常、保留页与缺失内容',items))
    method=[
        ('p','修正原因：旧脚本把每个 Data 字当成连续30位导航字。实测应将 Data[0] 的 bit29..4 映射为 ICD 位1..26，'
         'Data[1..9] 的低22位映射为各 ICD 字前22位；在对应校验位位置插入占位零，仅用于沿用 ICD 位号。'
         '高位未作为信息位使用；本报告未独立重算星上 BCH 校验。此前“重新解交织”的推测未被采用。'),
        ('p','该布局由实测交叉验证：200条消息的前导码均为0x712，FraID均与载荷子帧ID一致；'
         '还原SOW均在一周范围内。GPST头时间减14秒换为BDT后，与SOW的差值全部为7秒。'
         '这说明时标关系一致；差值的设备内部成因未由日志单独确定。子帧1解得当前BDT周1087，等于GPS周2443减1356。'
         '厂家手册未明确给出低22位打包细节，跨固件使用仍应核对。'),
        ('p','ASCII CRC：对 # 与 * 之间的原始ASCII字节计算反射CRC32，多项式0xEDB88320，初值0，最终异或0。'
         '保留原始字母大小写计算。补码：先按表中顺序拼接字段；若最高位为1，以无符号整数减2^字段宽度得到有符号整数。'),
        ('table',['字段','ICD 位段（1基）','符号','比例因子 / 单位'],
         [[n,', '.join(f'{s}-{s+l-1}' for s,l in parts),'补码' if signed else '无符号',f'2^{pow_} / {unit}']
          for n,parts,signed,pow_,unit in LAYOUT]),
        ('p','跨字字段按列出的 MSB 段、LSB 段依次拼接；角度由半周乘 pi 得到 rad，半长轴 A=(sqrt(A))^2。'
         '本报告只解析广播历书参数，不执行卫星位置外推，也不以广播星历替代历书。'),
    ]
    result.append(('位布局、比例因子与验证',method))
    g=good[0]
    worked=[('p',f'以 {g["id"]} / C16 为例，取原文件第{g["source_lines"][0]}行。转播卫星为C21，子帧4页16。'
             '原始十个Data字依次为：'),
            ('p',' '.join(g['data_words_hex'])),
            ('table',['字段','原始无符号值','补码后整数','换算结果'],
             [[t['parameter'],str(t['unsigned_integer']),str(t['integer']),f'{t["scaled_value"]:.12g} {t["unit"]}'] for t in g['trace']]),
            ('p','例如 a1 的原始11位整数为2042，最高位为1，因此2042-2048=-6；'
             'a1=-6*2^-38=-2.18278728425503e-11 s/s。sqrt(A)=(3<<22)+715996=13298908；'
             '乘2^-11得到6493.607421875 m^0.5，再平方得42166937.349430084 m。'),
            ('p','所有组的完整二进制位串、无符号值、补码整数、比例因子、单位、源行、转播卫星和原始消息见JSON；'
             'CSV提供全部参数版本和200条消息审核表。报告没有以重复转播条数替代独立目标数量。'),
            ('p','参考资料：')]
    for title,url in SOURCES:
        worked.append(('p',title+'：'+url))
    worked.append(('p','来源说明：官方 B1I PDF 本次直接下载失败；字段和比例因子使用 GNSS-SDR 原始定义复核，'
                   '扩展卫星映射另与北斗官方 B3I ICD 的共用D1定义核对。旧说明中把 B3I PDF 标成 B1I v3.0 的引用已更正。'))
    result.append(('计算示例、输出文件与来源',worked))
    return result


def write_html(parts):
    fragments=[]
    for title,items in parts:
        fragments.append('<section><h2>'+html.escape(title)+'</h2>')
        for item in items:
            if item[0]=='p':fragments.append('<p>'+html.escape(item[1])+'</p>')
            else:
                fragments.append('<table><thead><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in item[1])+'</tr></thead><tbody>')
                for row in item[2]:fragments.append('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in row)+'</tr>')
                fragments.append('</tbody></table>')
        fragments.append('</section>')
    (OUT/'UT986_almanac_report.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>UT986 北斗历书解析报告</title>
<style>body{font:15px/1.75 "Microsoft YaHei",sans-serif;color:#183047;max-width:1120px;margin:40px auto;padding:0 30px}h1{font-size:30px}h2{font-size:22px;border-bottom:2px solid #217a91;padding-bottom:10px}section{margin:45px 0}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #d7e0e6;padding:8px;text-align:left}th{background:#e8f0f5}p{overflow-wrap:anywhere}@media print{section{break-before:page}body{margin:0}}</style>
<h1>UT986 北斗历书解析报告</h1><p>数据：bdsrawsubfram_message.txt · 生成日期：2026-11-24</p>'''+''.join(fragments)+'</html>',encoding='utf-8')


def write_pdf(parts):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.pagesizes import A4
    pdfmetrics.registerFont(TTFont('Chinese',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
    style=ParagraphStyle('body',fontName='Chinese',fontSize=9,leading=14,spaceAfter=9,wordWrap='CJK')
    small=ParagraphStyle('cell',parent=style,fontSize=7.2,leading=10,spaceAfter=0)
    title_style=ParagraphStyle('title',parent=style,fontSize=19,leading=27,spaceAfter=17,textColor=colors.HexColor('#183047'))
    hstyle=ParagraphStyle('h2',parent=style,fontSize=15,leading=22,spaceAfter=14,textColor=colors.HexColor('#17697f'))
    para=lambda s,st=style:Paragraph(html.escape(s),st)
    story=[]
    for i,(title,items) in enumerate(parts):
        if i:story.append(PageBreak())
        if i==0:
            story.extend([para('UT986 北斗历书解析报告',title_style),para('采集数据解析 / 2026-11-24')])
        story.append(para(title,hstyle))
        for item in items:
            if item[0]=='p':story.append(para(item[1]))
            else:
                rows=[[para(x,small) for x in row] for row in [item[1]]+item[2]]
                n=len(item[1]);width=499
                if item[1][0]=='参数': widths=[112]+[(width-112)/(n-1)]*(n-1)
                elif n==6:widths=[35,40,65,125,130,104]
                else:widths=[width/n]*n
                table=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e6eff5')),
                    ('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#d1dce3')),
                    ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),
                    ('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                story.extend([table,Spacer(1,12)])
    def footer(canvas,doc):
        canvas.setFont('Chinese',8);canvas.setFillColor(colors.HexColor('#647585'))
        canvas.drawString(48,28,'UT986 / BDS D1 Almanac / 2026-11-24')
        canvas.drawRightString(A4[0]-48,28,str(doc.page))
    folder=OUT/'pdf';folder.mkdir(exist_ok=True)
    SimpleDocTemplate(str(folder/'UT986_almanac_report.pdf'),pagesize=A4,
        leftMargin=48,rightMargin=48,topMargin=40,bottomMargin=45,
        title='UT986 北斗历书解析报告',author='Codex').build(story,onFirstPage=footer,onLaterPages=footer)


if __name__=='__main__':
    report=analyze();save_data(report);parts=sections(report);write_html(parts);write_pdf(parts)
    print(json.dumps(dict(messages=len(report['records']),errors=report['errors'],
                         counts=report['counts'],groups=len(report['groups']),
                         nonzero_groups=report['good_group_ids'],output=str(OUT)),ensure_ascii=False,indent=2))
