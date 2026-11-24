"""Create per-stage reports and a verified-layout consolidated PDF."""
from pathlib import Path
import csv,html,json,math
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/position_comparison'


def readcsv(name):
    with (OUT/name).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def build_sections():
    s=json.loads((OUT/'comparison_summary.json').read_text(encoding='utf-8'))
    audit=json.loads((OUT/'step1_decoded_almanacs.json').read_text(encoding='utf-8'))
    validation=json.loads((OUT/'validation_results.json').read_text())
    gs=[g for g in audit['groups'] if not g['issues']]
    alm=readcsv('step3_almanac_positions.csv');bc=readcsv('step6_broadcast_positions.csv')
    o=s['overall_preferred_variant'];good=lambda n:f'{n:.3f}'
    p=lambda x:('p',x)
    table=lambda h,r:('table',h,[[str(v) for v in row] for row in r])
    result=[]
    result.append(('总览与结论',[
        p('本报告复核 UT986 原始导航消息中的北斗历书，分别实现历书与广播星历的卫星位置解算，'
          '在相同系统时刻、BDCS 地固坐标下比较三维位置。计算对象是历书目标卫星，不是转播该历书的卫星。'),
        p('原始日志包含200条完整消息、29个不同时间，时间范围为2026年11月5日03:43:51至03:46:39 UTC。'
          '232个历书位置已计算；C19、C20、C21存在可匹配的外部广播星历，共形成174条分版本比较记录。'),
        table(['目标','主版本 toa 秒','样本数','三维 RMS 米','三维最小 米','三维最大 米'],
              [[f'C{x["prn"]:02d}',x['toa_s'],x['N'],good(x['rms_3d_m']),good(x['min_3d_m']),good(x['max_3d_m'])]
               for x in s['statistics'] if x['toa_s']==94208]),
        p(f'主表采用每颗卫星较大的 toa 版本94208秒，三个目标等权统计，共{o["N"]}点：'
          f'三维均值{o["mean_3d_m"]:.3f}米，RMS {o["rms_3d_m"]:.3f}米，范围'
          f'{o["min_3d_m"]:.3f}至{o["max_3d_m"]:.3f}米。toa=86016秒的另三个版本单独列在步骤7，不混合计权。'),
        p('C16和C62的历书位置已给出；武汉大学下载的IGS与DLR文件均没有这两个PRN，无法给出其外部广播星历位置或偏差。'
          '日志没有WNa和历书健康页，全部历书传播结果以ICD最近半周归算为条件，不能据此确认绝对历书年龄与健康状态。'),
        p('历书偏差是相对广播星历模型的位置差，不是相对精密轨道的绝对误差。算法交叉验证通过并不消除输入历书过期、'
          '缺失健康标志或轨道类型假设所带来的限制。'),
        table(['步骤','执行结果'],[
            ['1 历书解析','200条CRC通过；8组非零参数；保留全零、异常和保留页诊断'],
            ['2 历书位置代码','独立二分法与旋转矩阵48例通过，含跨周边界'],
            ['3 历书位置','8组参数在29个消息头时刻计算232点'],
            ['4 下载广播星历','从武大下载2026年第309日IGS和DLR文件，MD5与目录一致'],
            ['5 广播星历位置代码','独立RTKLIB解析与3552个位置交叉校验通过'],
            ['6 广播星历位置','C19-C21共87点；C16和C62缺参考'],
            ['7 同时刻偏差统计','6个版本分别统计174点；主版本总计87点']]),
    ]))
    result.append(('步骤1 历书参数解析与复核',[
        p('和芯星通官方协议手册CH R2.0正文87至88页规定了BDSRAWSUBFRAME的消息载荷、十个Data字和接收机奇偶校验行为；'
          '手册把导航字段的语义交给北斗ICD。历书位段与比例因子按D1格式图5-11-1及5-11-6，并以GNSS-SDR原始定义复核。'),
        p('本批次信息位的还原方法为：Data[0]的bit29..4映射ICD位1..26；Data[1..9]各自低22位映射对应导航字前22位。'
          '剩余校验位位置补零，只为沿用ICD位号；高位没有当成导航信息。此布局通过全部消息前导码、FraID、SOW、当前周和重复转播一致性核对；'
          '厂家手册未明确该打包位序，不能把本次核对当作跨固件保证。'),
        p('ASCII CRC采用多项式0xEDB88320，初值0、最终异或0，对#与*之间的原始ASCII计算。'
          '200条全部通过。160个字段使用原生RTKLIB位提取函数交叉核对。代码还测试了CRC破坏必须拒绝、字段补码和跨字拼接。'),
        table(['组','目标','toa 秒','sqrt A','偏心率','原始源行'],
            [[g['id'],f'C{g["almanac"]["prn"]:02d}',g['almanac']['toa_s'],
              f'{g["almanac"]["sqrt_a_m_half"]:.9f}',f'{g["almanac"]["eccentricity"]:.10f}',g['source_lines'][0]] for g in gs]),
        p('C19-C21每颗各有两版：六颗转播卫星提供toa=94208秒版本，C09提供toa=86016秒版本。'
          'C16存在全零替代页；C17、C18仅有全零轨道；C63的候选有超周toa或异常半长轴。'
          'AmID=11的扩展页18至21为保留页，不应解成轨道。'),
        p('232个历书位置仅使用非零、范围检查通过的8组。全部原始二进制位段、整数、符号扩展、单位和源行见'
          'step1_decoded_almanacs.json；先前报告中的错误位布局已修正。'),
    ]))
    result.append(('步骤2 根据历书计算卫星位置的代码',[
        p('代码入口为bds_position.py中的almanac_position。输入为解析所得的历书参数字典、BDT周内秒和轨道类型；'
          '输出为BDCS地固坐标X、Y、Z，单位米。采用北斗D1 ICD历书用户算法。'),
        p('取地心引力常数mu=3.986004418e14 m^3/s^2，地球自转角速度we=7.2921150e-5 rad/s。'
          '半长轴A=(sqrt A)^2，平均角速度n=sqrt(mu/A^3)，传播时间tk=t-toa按半周归算到正负302400秒内。'),
        p('平均近点角M=M0+n*tk。求解E-e*sin(E)=M，再用atan2求真近点角v；纬度幅角u=v+omega，'
          '轨道半径r=A*(1-e*cos(E))。牛顿迭代设置50次上限，并检查残差。'),
        p('参考倾角：MEO和IGSO使用0.30*pi，GEO使用0；完整倾角为参考倾角加delta_i。'
          '升交点经度O=Omega0+(Omega_dot-we)*tk-we*toa。先算轨道面x=r*cos(u)、y=r*sin(u)，再旋转到地固系。'),
        p('地固分量：X=x*cos(O)-y*cos(i)*sin(O)；Y=x*sin(O)+y*cos(i)*cos(O)；Z=y*sin(i)。'
          '这是历书的GEO/MEO/IGSO共同公式，不能把广播星历GEO的负5度旋转套进该历书公式。'),
        p('对本段C19-C21按MEO处理；C16按IGSO、C62按GEO处理。后两者因缺外部星历，轨道类型与位置结果仅作为条件结果，'
          '尚未获得当天外部轨道确认。钟差参数a0、a1不改变给定系统时刻的轨道坐标；本任务未用卫星钟时替代系统时。'),
        table(['验证','数量','结果'],[
            ['独立二分法解E与矩阵旋转','48例','与主算法最大差约1.073e-7米'],
            ['解析圆轨道参考','t=toa=0','满足位置[A,0,0]'],
            ['开普勒残差','含e=0.99','残差小于1e-13弧度'],
            ['跨周边界','0及604799秒等','按半周归算，独立算法一致']]),
        p('独立算法采用二分法和Numpy三维矩阵相乘，不调用主算法的旋转与迭代辅助函数。'
          '这验证数值实现一致性；不代替对缺失历书周号、健康状态和输入数据年龄的确认。'),
    ]))
    # Representative first epoch: all five targets, both almanac variants kept in machine-readable output.
    first=min(float(x['gps_tow_ms']) for x in alm)
    sample=[x for x in alm if float(x['gps_tow_ms'])==first and (x['prn'] in ['16','62'] or x['toa_s']=='94208')]
    result.append(('步骤3 消息时间对应的历书卫星位置',[
        p('主计算使用消息头的GPS周2443与毫秒周内秒359049000至359217000，每6秒一个时刻。'
          'GPST减14秒得到BDT，GPST减18秒得到UTC；因此BDT周1087、SOW范围为359035至359203秒。'),
        p('消息内导航子帧的SOW为359028至359196秒，比消息头转换后的BDT时间均早7秒。'
          '主CSV明确使用消息头时刻，另生成subframe_sow_positions.csv，保存33条非零历书消息在各自嵌入SOW时刻的结果。'),
        p('对8组历书分别在全部29个时刻计算，输出232个坐标。此为离线统一时间网格；部分历书在日志稍后才出现，'
          '对更早网格点的计算属于回算，不声称当时实时可获得这些历书。'),
        table(['目标','toa 秒','X 米','Y 米','Z 米'],
              [[f'C{int(x["prn"]):02d}',x['toa_s'],*[f'{float(x[k]):.3f}' for k in ['x_m','y_m','z_m']]] for x in sample]),
        p('上表为首个时刻2026-11-05 03:43:51 UTC，即BDT周内秒359035。所有坐标保留双精度原值导出，表中仅显示毫米位。'
          '显示到毫米不意味着历书具有毫米精度。'),
        p('缺少WNa时，采用ICD半周归算给出条件位置，不把当前BDT周1087填写为已知历书周。'
          '例如toa=94208秒时，tk=264827秒；toa=86016秒时，tk=273019秒。C62的toa=548864秒给出负tk。'),
        p('坐标为请求时刻的卫星地固坐标，未做信号飞行时间、接收机距离、站心转换、天线相位中心或传播Sagnac修正。'
          '两种轨道使用同一口径，避免把发射时刻和接收时刻混在一起。'),
        p('结果文件：step3_almanac_positions.csv；每行包含目标PRN、参数组、toa、GPST、UTC、BDT、tk及XYZ。'),
    ]))
    receipt=s['download_receipt']
    result.append(('步骤4 下载同一天的广播星历',[
        p('按照用户指定入口http://www.igs.gnsswhu.cn/index.php，检查页面脚本后使用其公开的只读检索接口'
          '/index.php/igs/gbxlList，查询2026-11-05。该日为2026年第309日，不采用2026年第310日文件。'),
        p('从检索返回的记录ID下载IGS混合广播星历388693和DLR混合广播星历388700；均为RINEX 3.04。'
          '检索JSON、原始HTTP响应、清理后的gzip、解压RINEX和下载校验回执均保存在reference_data目录。'),
        table(['文件','有效gzip字节','北斗记录数','有效gzip的MD5'],
              [[x['filename'].replace('_20263090000_01D_MN.rnx.gz',''),x['gzip_member_bytes'],
                s['nav_bds_records'] if x['filename'].startswith('BRDC') else s['dlr_bds_records'],x['md5']] for x in receipt]),
        p('武汉大学的下载响应在合法gzip结束后附加19454字节网页调试HTML。使用zlib流解码确认gzip完整结束，只截取已验证的gzip成员；'
          '截取后的MD5分别与网站检索列表完全相同。未对RINEX导航参数做任何编辑。原始HTTP响应保留以便复核。'),
        p('IGS有效gzip SHA-256：'+next(x['sha256'] for x in receipt if x['filename'].startswith('BRDC'))),
        p('DLR有效gzip SHA-256：'+next(x['sha256'] for x in receipt if x['filename'].startswith('BRDM'))),
        p('两份文件都包含C19-C21，但均未包含C16和C62。IGS文件有888条BDS记录，DLR文件有866条；'
          '未用其他PRN替代C16或C62，也未把同一历书转播卫星的星历当作目标卫星星历。'),
        p('补充检查了武大同日BRD400DLR的RINEX 4文件，目录记录ID388653，gzip的MD5也与目录一致。'
          '该文件中C16与C62的星历记录数仍均为0。此文件只用于覆盖检查，不送入传统RINEX 3传播解析器；'
          '覆盖证据保存于reference_data/rinex4_coverage_check.json。'),
        p('复现入口：fetch_reference_data.py；首次从公开网页下载，已有缓存时重验gzip完整性和目录MD5。'
          '最初FTP与镜像访问诊断保存在download_log.json；最终采用武大网页文件，准确来源以download_receipt.json为准。'),
    ]))
    result.append(('步骤5 根据广播星历计算卫星位置的代码',[
        p('bds_position.py中的read_rinex3_bds按固定列宽读取RINEX 3北斗传统导航记录；'
          'BDS记录的toc日历与week均按BDT解释。广播星历位置由broadcast_position计算，星历选择由select_ephemeris完成。'),
        p('在历书的开普勒模型基础上加入delta_n、IDOT及Cuc、Cus、Crc、Crs、Cic、Cis六个谐波项。'
          '先根据未改正纬度幅角计算二倍角正余弦，再改正纬度幅角、半径与倾角。toe绝对时刻由BDT周和周内秒组成，'
          '不用跨周取模掩盖过期广播星历。'),
        p('MEO和IGSO使用Omega0+(Omega_dot-we)*tk-we*toe。GEO使用Omega0+Omega_dot*tk-we*toe，'
          '在中间坐标系计算后按ICD负5度倾斜与地球自转旋转至BDCS。'),
        p('选择规则是健康标志为0、toc与toe不晚于目标时刻、toe年龄不超过3600秒、播发时间符合过去窗口。'
          '本段C19-C21均选中BDT当天03:00、toe=356400秒的星历；没有使用04:00的未来星历来改善差值。'),
        table(['独立验证项目','规模','结果'],[
            ['原生RTKLIB独立读取RINEX','888条星历 13320字段','逐字段一致'],
            ['原生RTKLIB eph2pos','3552个点，含GEO','最大三维差2.979417e-7米'],
            ['IGS与DLR交叉文件','87个目标位置','最大差0.000117707米'],
            ['位置比较阈值','0.001米','独立实现核对通过']]),
        p('原生RTKLIB验证使用固定版本pyrtklib 0.2.7，与生产代码独立解析和传播。'
          '选取每条BDS星历在toe后的0、600、2700和3599秒共4点，覆盖所有37个BDS PRN与GEO分支。'
          '交叉实现达到微米以下只是浮点数实现一致性，不能解释为广播轨道真实误差。'),
        p('代码拒绝RINEX 4和现代CNAV模型，避免把不同模型字段当作传统星历解析。'
          '验证入口validate_bds_position.py，执行结果见validation_results.json。'),
    ]))
    first_bc=[x for x in bc if float(x['gps_tow_ms'])==first]
    result.append(('步骤6 同一消息时刻的广播星历位置',[
        p('以步骤3相同的29个消息头时刻、相同BDT绝对秒和相同BDCS坐标系计算C19、C20、C21，共87个位置。'
          'C16和C62的58个目标时刻记录缺少参考，列入step6_missing_reference.csv，不用零坐标占位参与统计。'),
        table(['目标','X 米','Y 米','Z 米','toe年龄 秒'],
              [[f'C{int(x["prn"]):02d}',*[f'{float(x[k]):.3f}' for k in ['x_m','y_m','z_m']],
                f'{float(x["toe_age_s"]):.0f}'] for x in first_bc]),
        p('上表对应2026-11-05 03:43:51 UTC，即BDT周1087、SOW=359035秒。'
          'toe年龄从首点2635秒增加到末点2803秒，始终位于选取的一小时窗口。'),
        p('step6_broadcast_positions.csv保留每个目标时刻的XYZ、UTC、GPST、BDT绝对秒、健康状态、'
          'toe、AODE及原始RINEX源行。step7_position_differences.csv将对应时刻的两套XYZ并排保存，便于逐行复算。'),
        p('对消息内部子帧SOW的附加比较另存subframe_sow_positions.csv，不混入主网格统计。'
          '这样既能复核“消息头时间”的含义，也能复核“电文子帧时间”的含义；二者的7秒差异可造成显著位置变化。'),
        p('广播星历是对比基准模型。此处不求伪距、不估算接收机位置、不进行卫星钟差与电离层/对流层修正。'
          '用户给定系统时刻的几何轨道位置不需要这些测量模型。'),
    ]))
    result.append(('步骤7 同时刻位置偏差与统计',[
        p('定义dX=X历书-X广播，dY和dZ同理；三维差d3=sqrt(dX^2+dY^2+dZ^2)。'
          '三维RMS=sqrt(mean(d3^2))；分量RMS=sqrt(mean(dX^2))等；标准差使用总体定义。'
          '每个参数版本在29个不重复时刻各占一个样本，多颗转播卫星的重复消息不重复计权。'),
        table(['目标','toa 秒','N','三维均值 米','三维RMS 米','最小 米','最大 米'],
              [[f'C{x["prn"]:02d}',x['toa_s'],x['N'],good(x['mean_3d_m']),good(x['rms_3d_m']),
                good(x['min_3d_m']),good(x['max_3d_m'])] for x in s['statistics']]),
        table(['目标和版本','均值dX 米','均值dY 米','均值dZ 米'],
              [[f'C{x["prn"]:02d} / {x["toa_s"]}',good(x['mean_dx_m']),good(x['mean_dy_m']),
                good(x['mean_dz_m'])] for x in s['statistics']]),
        p('主统计采用较大的toa=94208秒版本，得到整体三维RMS 976.819米。'
          '该版本选择仅用于避免一颗卫星的两套参数重复计权，不代表已知WNa下已确认其绝对年龄更新，'
          '也不是按更小误差事后挑选版本。所有旧版本结果一并保留。'),
        p('主版本约0.9至1.0千米差异是本段3分钟范围内相对广播星历的位置差，不能外推为所有时刻或所有北斗历书的精度。'
          '缺少WNa使此结果带有最近半周的年龄假设；缺少健康页使历书健康状态不可判定。C16和C62没有外部误差结论。'),
        p('工程复现：先运行fetch_reference_data.py，再运行validate_bds_position.py，最后运行run_bds_comparison.py'
          '与generate_position_report.py。Python依赖和完整命令见README_BDS_POSITION.md；各步骤HTML、CSV、JSON和汇总PDF保存在本目录。'),
        p('参考：UT986官方手册CH R2.0正文87至88页；BDS B1I ICD v3.0历书与星历用户算法；'
          'GNSS-SDR Beidou_DNAV.h原始字段定义；RTKLIB eph2pos实现与pyrtklib 0.2.7独立计算；'
          '武大公开导航文件检索及两个下载回执。官方B1I PDF此前直链下载未成功，相关位段使用原始开源定义复核，'
          '官方B3I ICD的共用D1定义用于扩展页映射复核。'),
    ]))
    return result


def write_html(sections):
    css='body{font:15px/1.7 Microsoft YaHei,sans-serif;max-width:1100px;margin:40px auto;color:#202b33}h1{font-size:28px}h2{font-size:22px}table{border-collapse:collapse;width:100%;font-size:13px;margin:20px 0}th,td{padding:8px;border:1px solid #ccd3d9}th{background:#e8edf2}p{overflow-wrap:anywhere}section{margin-bottom:50px}'
    all_fragments=[]
    for i,(title,items) in enumerate(sections):
        fragment='<section><h2>'+html.escape(title)+'</h2>'
        for it in items:
            if it[0]=='p':fragment+='<p>'+html.escape(it[1])+'</p>'
            else:
                fragment+='<table><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in it[1])+'</tr>'
                for row in it[2]:fragment+='<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in row)+'</tr>'
                fragment+='</table>'
        fragment+='</section>';all_fragments.append(fragment)
        filename='step'+str(i)+'_report.html' if i else 'overview_report.html'
        (OUT/filename).write_text('<!doctype html><meta charset="utf-8"><style>'+css+'</style>'+fragment,encoding='utf-8')
    (OUT/'BDS_position_comparison_report.html').write_text('<!doctype html><meta charset="utf-8"><title>北斗历书与广播星历位置对比报告</title><style>'+css+'</style><h1>北斗历书与广播星历位置对比报告</h1>'+''.join(all_fragments),encoding='utf-8')


def write_pdf(sections):
    pdfmetrics.registerFont(TTFont('CJK',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
    body=ParagraphStyle('body',fontName='CJK',fontSize=9.5,leading=15,spaceAfter=12,wordWrap='CJK')
    cell=ParagraphStyle('cell',parent=body,fontSize=8,leading=12,spaceAfter=0)
    title=ParagraphStyle('title',parent=body,fontSize=19,leading=27,spaceAfter=18)
    head=ParagraphStyle('head',parent=body,fontSize=15,leading=23,spaceAfter=16)
    para=lambda t,s=body:Paragraph(html.escape(t),s)
    story=[]
    for idx,(name,items) in enumerate(sections):
        if idx:story.append(PageBreak())
        if not idx:story.extend([para('北斗历书与广播星历位置对比报告',title),para('UT986原始消息  观测日2026年11月5日  报告日期2026年11月24日')])
        story.append(para(name,head))
        for it in items:
            if it[0]=='p':story.append(para(it[1]))
            else:
                rows=[[para(x,cell) for x in row] for row in [it[1]]+it[2]]
                n=len(it[1]);width=499
                if n==2:widths=[114,385]
                elif n==3:widths=[235,100,164]
                elif n==5 and it[1][1]=='toa 秒':widths=[44,65,130,130,130]
                elif n==5:widths=[44,125,125,125,80]
                elif n==6:widths=[44,70,56,110,110,109]
                elif n==4 and it[1][0]=='文件':widths=[130,80,64,225]
                else:widths=[width/n]*n
                table=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8edf2')),
                    ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd3d9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                story.extend([table,Spacer(1,14)])
    def footer(c,d):
        c.setFont('CJK',8);c.setFillColor(colors.HexColor('#64717c'))
        c.drawString(48,27,'BDS 卫星位置计算与比对  2026-11-05')
        c.drawRightString(A4[0]-48,27,str(d.page))
    SimpleDocTemplate(str(OUT/'BDS_position_comparison_report.pdf'),pagesize=A4,
        leftMargin=48,rightMargin=48,topMargin=38,bottomMargin=44,
        title='北斗历书与广播星历位置对比报告',author='Codex').build(story,onFirstPage=footer,onLaterPages=footer)


if __name__=='__main__':
    parts=build_sections();write_html(parts);write_pdf(parts)
    print(OUT/'BDS_position_comparison_report.pdf')
