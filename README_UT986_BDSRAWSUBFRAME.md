# UT986 `BDSRAWSUBFRAME` 历书解析

已下载官方协议手册：
[UT986_GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf](UT986_GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf)。
下载来源为和芯星通的[官方链接](https://www.unicorecomm.com/assets/upload/file/GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf)，版本为 `UC-04-M37 CH R2.0`。

## 使用

把完整的一行 `#BDSRAWSUBFRAME...` 交给脚本：

```powershell
python .\bds_rawsubframe_almanac.py --json '#BDSRAWSUBFRAME,...;channel,satellite,source,subframe,Data0,Data1,Data2,Data3,Data4,Data5,Data6,Data7,Data8,Data9*CRC'
```

也可以从标准输入读取：

```powershell
Get-Content .\one_message.txt | python .\bds_rawsubframe_almanac.py --json
```

## 已实现的电文范围

解析器针对 BDS **D1** 格式：子帧 4 的页 1–24 和子帧 5 的页 1–6，承载 PRN 1–30。
还支持同源 AmEpID=3 上下文下的子帧5扩展页：AmID=1 的页11–23对应C31–43，AmID=2对应C44–56，AmID=3的页11–17对应C57–63，其余组合不解为轨道。
单行命令的扩展上下文通过 `--expanded-context 3` 显式传入；批量报告按转播卫星与帧自动跟踪。
每条成功的结果包含：

| 参数 | ICD 位段 | 原始量与换算 |
|---|---|---|
| `sqrt_a` | 51–52, 61–82 | 无符号，`2^-11 m^1/2`；同时给出 `A=(sqrt_a)^2` |
| `a1` / `a0` | 91–101 / 102–112 | 补码，`2^-38 s/s` / `2^-20 s` |
| `omega0` | 121–142, 151–152 | 补码，`2^-23` 半周；也输出弧度 |
| `e` | 153–169 | 无符号，`2^-21` |
| `delta_i` | 170–172, 181–193 | 补码，`2^-19` 半周；也输出弧度 |
| `toa` | 194–201 | 无符号，`2^12 s` |
| `omega_dot` | 202, 211–226 | 补码，`2^-38` 半周/s；也输出 rad/s |
| `omega` | 227–232, 241–258 | 补码，`2^-23` 半周；也输出弧度 |
| `M0` | 259–262, 271–290 | 补码，`2^-23` 半周；也输出弧度 |
| `AmEpID` | 291–292 | 无符号扩展历书标识 |

位号是 BDS SIS ICD 的 1 基、MSB 优先编号。按本文件的实际输出布局：`Data[0]` 的 bit29..4 对应首字26个信息位；`Data[1..9] & 0x3FFFFF` 提取各字22个信息位，再在 ICD 校验位位置补零以保留位号。高位没有被当作导航信息；本解析器不独立重算 BCH。此打包细节由本次日志的前导码、SOW、页号、周数与重复转播一致性核对，不应当作跨固件保证。

`BDSRAWSUBFRAME` 中的 `subframe ID` 会与导航字的 D1 `FraID` 交叉核对；ASCII CRC32 不通过时拒绝解析。批量报告区分非零候选、全零、异常、保留页与缺失上下文，不将健康/UTC页当作轨道历书。

## 批量解析与报告

运行 `python generate_almanac_report.py`，读取同目录的 `bdsrawsubfram_message.txt`，自动提取带接收前缀的完整消息并输出至 `output`。
报告含 PDF、HTML、全部参数 CSV、逐条消息审核 CSV 和包含原始位串的 JSON。当前批次缺少 WNa 和健康页，因此不能给出完整历书历元或认证健康状态。

## 参考

- [和芯星通 UT986 协议手册](https://www.unicorecomm.com/assets/upload/file/GNSS_Timing_Products_Protocol_Specification_CH_R2_0.pdf)：`BDSRAWSUBFRAME` 的 ASCII 载荷、`Data[0..9]` 和接收机校验行为。
- [北斗 B1I SIS ICD v3.0](https://en.beidou.gov.cn/SYSTEMS/ICD/201902/P020190227702348791891.pdf)：D1 历书定义；本次官方PDF下载失败。
- [GNSS-SDR 原始参数定义](https://github.com/gnss-sdr/gnss-sdr/blob/main/src/core/system_parameters/Beidou_DNAV.h)：字段位置和比例因子复核。
- [北斗 B3I SIS ICD v1.0](https://en.beidou.gov.cn/SYSTEMS/ICD/201806/P020180608516798097666.pdf)：共用D1结构与扩展页映射复核；此链接不是B1I v3.0。
