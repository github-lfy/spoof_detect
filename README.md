# UT986 北斗历书解析与卫星位置比较

解析和芯星通 UT986 的 `BDSRAWSUBFRAME` 消息，提取北斗 D1 基本及扩展历书，计算卫星地固位置，并与同日广播星历位置比较。

## 功能

- ASCII CRC32 校验、导航信息位还原、补码及比例因子换算。
- 历书卫星位置计算，支持 MEO、IGSO、GEO 的参考倾角。
- RINEX 3 北斗传统广播星历读取与位置计算，包含广播星历 GEO 特殊旋转。
- 从武汉大学 IGS 数据中心下载广播星历并验证目录 MD5。
- 使用原生 RTKLIB 和独立数值实现交叉验证。
- 导出逐点坐标、位置偏差、统计、TXT、HTML 和 PDF 报告。

## 安装

需要 Python 3.10+。在工程目录执行：

```sh
python -m pip install -r requirements.txt
```

独立验证所用的 `pyrtklib` 需要适配当前 Python 与平台的预编译安装包。生产位置算法只使用 Python 标准库。
PDF 生成器默认使用 Windows 微软雅黑字体；在其他系统运行时需调整报告脚本中的字体路径。

## 运行

将自己的接收日志保存为工程目录中的 `bdsrawsubfram_message.txt`。接收日志可以包含其他文本，批量解析器提取其中完整消息。

```sh
python generate_almanac_report.py
python fetch_reference_data.py
python validate_bds_position.py
python run_bds_comparison.py
python generate_position_report.py
python export_results_txt.py
```

当前下载与比对脚本针对已分析的观测日 **2026-11-05**。用于其他日期时，需要修改下载检索日期及文件选择，并确认时间系统转换和轨道分类。

详细接口、输出文件和复现说明见 [README_BDS_POSITION.md](README_BDS_POSITION.md)；消息格式说明见 [README_UT986_BDSRAWSUBFRAME.md](README_UT986_BDSRAWSUBFRAME.md)。

## 本次计算结果和报告

- [位置对比汇总报告 PDF](output/position_comparison/BDS_position_comparison_report.pdf)
- [位置对比汇总报告 HTML](output/position_comparison/BDS_position_comparison_report.html)
- [历书参数解析报告 PDF](output/pdf/UT986_almanac_report.pdf)
- [各卫星历书参数 TXT](output/position_comparison/txt/BDS_各卫星历书参数.txt)
- [两套位置与逐点偏差 TXT](output/position_comparison/txt/BDS_历书位置_广播星历位置_位置偏差.txt)
- [偏差统计 TXT](output/position_comparison/txt/BDS_位置偏差统计.txt)
- [独立算法验证结果](output/position_comparison/validation_results.json)

2026-11-05 的29个消息头时刻中，C19、C20、C21主版本的三维RMS分别为1040.302、893.341和991.079米，整体RMS为976.819米。
C16、C62缺少同日目标广播星历，未计入偏差统计。结果是相对广播星历模型的位置差，不是相对真实轨道的绝对误差。

## 主要文件

| 文件 | 功能 |
|---|---|
| `bds_rawsubframe_almanac.py` | CRC、信息位还原、历书字段提取 |
| `generate_almanac_report.py` | 按转播卫星跟踪扩展标识与批量解析 |
| `bds_position.py` | 历书与广播星历位置算法 |
| `validate_bds_position.py` | 独立算法验证 |
| `fetch_reference_data.py` | 广播星历下载及完整性校验 |
| `run_bds_comparison.py` | 统一时刻计算与偏差统计 |
| `generate_position_report.py` | 分步骤报告和汇总报告 |
| `export_results_txt.py` | 参数与位置结果的 TXT 导出 |

## 数据解释

坐标为 BDCS 地固坐标，单位米。主比较采用消息头系统时刻，不含信号飞行时间、接收机位置或天线相位中心修正。
历书缺少 WNa 或健康信息时，输出只能按 ICD 最近半周规则作条件传播，不能确认其绝对年龄或健康状态。
输入打包布局已对本批 UT986 日志验证；其他固件应重新核对。缺失的目标广播星历不能用转播卫星星历替代。

源代码不依赖项目中预存的原始对话日志、厂商 PDF、广播星历缓存或生成结果；复现计算需自行提供输入消息并下载参考数据。
