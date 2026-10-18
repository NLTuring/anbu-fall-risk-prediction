# 安步 (AnBu) · 无穿戴步态量化与老龄跌倒风险预测系统

![Python](https://img.shields.io/badge/Edge-Python%20%2B%20RK3576%20Pose-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/Web-TypeScript%20%2B%20Vite-3178C6?logo=typescript&logoColor=white)
![Vision](https://img.shields.io/badge/Algorithm-YOLO%20Pose%20%2B%20Gait%20Analysis-008080)

> 让跌倒风险在迈出下一步之前被看见——零穿戴负担的边缘视觉步态分析与照护预警系统。

**安步（AnBu）** 是一套面向养老机构与居家老龄人群的无感步态监测与跌倒风险分层系统。系统无需老人佩戴手环或传感器，基于 **RK3576 边缘计算盒** 对日常走廊通行画面进行实时人体姿态估计（Pose Estimation）与步态运动学参数解算（步速、步幅对称性、双支撑相占比、躯干摆幅），并将脱敏后的风险趋势同步至**机构护理看板 (`web/`)**。

---

## 系统架构与核心模块

- **端侧姿态估计与步态解算服务 (`edge/`)**
  - **视觉姿态提取 (`edge/pose.py`)**：基于改进轻量级姿态估计网络提取下肢与躯干关键点序列，计算连续步态周期指标。
  - **边缘推理与守护服务 (`edge/service.py` / `systemd/`)**：原始视频流在 RK3576 设备端内存实时处理后即刻销毁（视频不出设备），仅输出结构化步态特征与风险分级；提供 `install.sh`、`run.sh`、`diagnose.sh` 及 Linux `systemd` 自启配置。
- **机构照护看板与趋势预警前端 (`web/`)**
  - 基于 TypeScript + Vite 构建，提供在院老人风险等级排序、个人多周步速/步态稳定性趋势曲线、异常波动告警与护理干预任务闭环跟踪。

---

## 快速启动

### 1. 启动 Web 照护风险看板 (`web/`)

环境要求：Node.js 20+。

```bash
cd web
npm ci
npm run dev
```

运行前端状态逻辑单元测试：

```bash
cd web
npm test
```

### 2. 启动边缘端步态服务 (`edge/`)

环境要求：Python 3.10+（支持 Linux / RK3576 边缘环境及本地开发调试）。

```bash
cd edge
pip install -r requirements.txt
bash run.sh
```

运行边缘端自动化测试：

```bash
pytest edge/tests
```

---

## 目录结构

```text
anbu-fall-risk-prediction/
├── edge/           # RK3576 边缘端姿态估计 (pose.py)、推理服务 (service.py)、systemd 部署脚本与测试
├── web/            # 机构照护风险看板前端源码 (TypeScript + Vite) 与单元测试
├── docs/           # 步态运动学指标体系、系统架构与产品方案文档
└── tools/          # 工程辅助脚本
```
