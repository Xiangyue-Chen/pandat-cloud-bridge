# 本机 Pandat 数据库清单

2026-10-28 使用 `D:\bin\Pandat.exe` 逐个实际加载本机 PDB，并从 Pandat 2024 TDB Viewer 元数据读取数据库级元素列表。共确认 21 个数据库，0 个缺失。机器可读的路径、SHA-256、启用状态和默认库见 [`config/databases.json`](../config/databases.json)。

| 数据库 | 元素数 | Pandat 报告的可用元素 |
| --- | ---: | --- |
| MDT Cu 2020 TH | 19 | Al, B, Bi, C, Cr, Cu, Fe, Mn, Ni, P, Pb, S, Sb, Se, Si, Sn, Ti, Zn, Zr |
| PanAl 2020 TH+MB | 34 | Ag, Al, B, Be, Bi, C, Ca, Ce, Co, Cr, Cu, Fe, Gd, Ge, Hf, K, Li, Mg, Mn, Na, Nb, Ni, Pb, Sb, Sc, Si, Sn, Sr, Ti, V, W, Y, Zn, Zr |
| PanAl 2022 TH+MB | 37 | Ag, Al, B, Ba, Be, Bi, C, Ca, Ce, Co, Cr, Cu, Er, Fe, Gd, Ge, Hf, K, La, Li, Mg, Mn, Na, Nb, Ni, Pb, Sb, Sc, Si, Sn, Sr, Ti, V, W, Y, Zn, Zr |
| PanAl 2023a TH+MB | 37 | Ag, Al, B, Ba, Be, Bi, C, Ca, Ce, Co, Cr, Cu, Er, Fe, Gd, Ge, Hf, K, La, Li, Mg, Mn, Na, Nb, Ni, Pb, Sb, Sc, Si, Sn, Sr, Ti, V, W, Y, Zn, Zr |
| PanAl 2024 TH+MB | 38 | Ag, Al, B, Ba, Be, Bi, C, Ca, Ce, Co, Cr, Cu, Er, Fe, Gd, Ge, Hf, K, La, Li, Mg, Mn, Na, Nb, Ni, O, Pb, Sb, Sc, Si, Sn, Sr, Ti, V, W, Y, Zn, Zr |
| PanCo 2020 TH | 18 | Al, B, C, Co, Cr, Cu, Fe, Mn, Mo, Nb, Ni, Pt, Re, Si, Ta, Ti, W, Zr |
| PanCo 2023 TH+MB | 19 | Al, B, C, Co, Cr, Cu, Fe, Mn, Mo, Nb, Ni, Pt, Re, Si, Ta, Ti, V, W, Zr |
| PanFe 2023 TH+MB | 30 | Al, As, B, C, Ca, Ce, Co, Cr, Cu, Fe, Mg, Mn, Mo, N, Nb, Ni, O, P, Pb, Pr, S, Si, Sn, Ta, Ti, V, W, Y, Zn, Zr |
| PanHEA 2022 TH+MB | 19 | Ag, Al, B, C, Co, Cr, Cu, Fe, Hf, Li, Mg, Mn, Mo, Ni, Si, Sn, Ti, V, Zr |
| PanHEA 2023 TH+MB | 20 | Ag, Al, B, C, Co, Cr, Cu, Fe, Hf, Li, Mg, Mn, Mo, Ni, Si, Sn, Ti, V, Zn, Zr |
| **PanHEA 2024 TH+MB（默认）** | **21** | Ag, Al, B, C, Co, Cr, Cu, Fe, Hf, Li, Mg, Mn, Mo, Ni, O, Si, Sn, Ti, V, Zn, Zr |
| PanMg 2022 TH+MB | 31 | Ag, Al, Bi, C, Ca, Ce, Co, Cu, Dy, Er, Fe, Gd, La, Li, Mg, Mn, Nd, Ni, O, P, Pr, Sb, Sc, Se, Si, Sm, Sn, Sr, Y, Zn, Zr |
| PanMg 2024 TH+MB | 31 | Ag, Al, Bi, C, Ca, Ce, Co, Cu, Dy, Er, Fe, Gd, La, Li, Mg, Mn, Nd, Ni, O, P, Pr, Sb, Sc, Se, Si, Sm, Sn, Sr, Y, Zn, Zr |
| PanNi 2020 TH | 22 | Al, B, C, Co, Cr, Cu, Fe, Hf, Ir, Mn, Mo, N, Nb, Ni, Pt, Re, Ru, Si, Ta, Ti, W, Zr |
| PanNi 2022 TH+MB | 27 | Al, B, C, Co, Cr, Cu, Fe, Hf, Ir, Mn, Mo, N, Nb, Ni, O, P, Pt, Re, Ru, S, Si, Ta, Ti, V, W, Y, Zr |
| PanNi 2023 TH+MB | 27 | Al, B, C, Co, Cr, Cu, Fe, Hf, Ir, Mn, Mo, N, Nb, Ni, O, P, Pt, Re, Ru, S, Si, Ta, Ti, V, W, Y, Zr |
| PanNi 2024 TH+MB | 27 | Al, B, C, Co, Cr, Cu, Fe, Hf, Ir, Mn, Mo, N, Nb, Ni, O, P, Pt, Re, Ru, S, Si, Ta, Ti, V, W, Y, Zr |
| PanRHEA 2023a TH+MB | 21 | Al, B, C, Co, Cr, Cu, Fe, H, Hf, Mn, Mo, N, Nb, Ni, O, Si, Ta, Ti, V, W, Zr |
| PanTi 2023 TH+MB | 21 | Al, B, C, Cr, Cu, Fe, H, Hf, Mn, Mo, N, Nb, Ni, O, Si, Sn, Ta, Ti, V, W, Zr |
| PanTiAl 2021 TH+MB | 16 | Al, B, C, Cr, Mn, Mo, N, Nb, O, Si, Sn, Ta, Ti, V, W, Zr |
| PanZr 2023 TH+MB | 8 | Cu, Fe, Nb, Ni, O, Sn, V, Zr |

这里的“可用元素”是数据库级 component 清单，不代表任意元素组合都已有完整热力学评估。实际计算仍可能因所选子体系、相模型或数据库覆盖范围而失败，失败会作为 Pandat 作业结果返回。
