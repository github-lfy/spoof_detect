# 北斗历书与广播星历位置对比

本工程从 UT986 BDSRAWSUBFRAME 提取 D1 历书，在消息头对应时刻计算 BDCS 地固位置，并与从武汉大学下载的同日广播星历计算值比较。

## 复现

本机可用 Python 是 `C:\Users\lfy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。
在本目录依次执行以下文件（用该绝对解释器路径，或自己的 Python 3.10+）：

```powershell
python fetch_reference_data.py
python validate_bds_position.py
python run_bds_comparison.py
python generate_position_report.py
```

依赖：`numpy`、`reportlab`（运行时已带），独立校验使用 `pyrtklib==0.2.7`，已安装在本工程 `vendor` 中，不修改系统环境。
缺失时安装到工程目录：`python -m pip install --target vendor --only-binary=:all: --no-deps pyrtklib==0.2.7`。
报告使用Windows微软雅黑字体；跨平台请在报告生成脚本中指定可用的中文TrueType字体。

## 代码接口

- `bds_rawsubframe_almanac.py`：ASCII CRC、低22位还原、D1基本/扩展历书提取；单行CLI支持 `--expanded-context 3`，调用方须确认同源同帧AmEpID。
- `bds_position.py`：`almanac_position(parameters, sow_bdt, orbit_type)` 返回 `(X,Y,Z)` 米；`read_rinex3_bds(path)` 读取传统BDS星历；`select_ephemeris` 返回健康、已播发、一小时toe窗口内的星历；`broadcast_position(eph, bdt_abs, orbit_type)` 返回 `(X,Y,Z)` 米。
- `validate_bds_position.py`：独立RTKLIB固定版本读取和传播、独立二分/矩阵历书解算、补码与跨周检查。
- `run_bds_comparison.py`：统一时间网格，导出位置、差值、按版本统计和完整回执。
- `generate_position_report.py`：将实算JSON/CSV生成各步骤HTML报告及汇总PDF。

## 数据与输出

输入 `bdsrawsubfram_message.txt` 含历史对话和接收日志，只提取完整消息，原文件不修改。
武汉大学只读接口及目录记录保存在 `reference_data/whu_broadcast_listing.json`。
HTTP响应中gzip尾部附有网页HTML：原始响应以 `WHU_*.gz` 保留，真正可直接gzip解压的文件为 `CLEAN_WHU_*.gz`；有效成员MD5与目录完全一致。
`reference_data/download_receipt.json` 是最终下载证明；旧 `download_log.json` 是初始失败诊断，不是最终数据来源。

所有新结果位于 `output/position_comparison`：

| 步骤 | 主要文件 |
|---|---|
| 1 | step1_report.html、step1_decoded_almanacs.json |
| 2 | step2_report.html、validation_results.json |
| 3 | step3_report.html、step3_almanac_positions.csv |
| 4 | step4_report.html、reference_data 下的下载文件和回执 |
| 5 | step5_report.html、validation_results.json |
| 6 | step6_report.html、step6_broadcast_positions.csv、step6_missing_reference.csv |
| 7 | step7_report.html、step7_position_differences.csv、step7_statistics.csv |
| 汇总 | BDS_position_comparison_report.pdf、BDS_position_comparison_report.html、comparison_summary.json |

主网格为29个消息头时刻；GPST减14秒转BDT、减18秒转该日期UTC。嵌入子帧SOW比消息头BDT早7秒，附加计算单列在 `subframe_sow_positions.csv`。
当前周为BDT1087，WNa缺失。历书按ICD半周规则传播，不能确认其绝对年龄；健康状态未知。C16按IGSO、C62按GEO为条件计算，两份外部星历均没有这两个PRN。
主比较为C19-C21；同目标多个toa分别统计。总统计采用每目标较大toa版本一次，避免重复计权；不按误差大小选版本。
还补查了武大同日 `BRD400DLR_S_20263090000_01D_MN.rnx.gz`，目录记录ID388653；C16和C62记录仍为0。此RINEX4只作覆盖检查，不当作传统星历解析。证据在 `reference_data/rinex4_coverage_check.json`。
只比较同一系统时刻的卫星几何地固坐标，不做天线、飞行时间、Sagnac、接收机位置或伪距计算。

## 参考

- [和芯星通官方协议手册](https://www.unicorecomm.com/assets/upload/file/GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf)
- [BDS B1I SIS ICD v3.0](https://en.beidou.gov.cn/SYSTEMS/ICD/201902/P020190227702348791891.pdf)
- [GNSS-SDR原始字段定义](https://github.com/gnss-sdr/gnss-sdr/blob/main/src/core/system_parameters/Beidou_DNAV.h)
- [RTKLIB星历实现](https://github.com/tomojitakasu/RTKLIB/blob/master/src/ephemeris.c)
- [pyrtklib原生绑定](https://github.com/IPNL-POLYU/pyrtklib)
- [武汉大学IGS数据中心](http://www.igs.gnsswhu.cn/index.php)
