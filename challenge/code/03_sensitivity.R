# 测试夹具（非真实分析脚本），仅用于 check_binning_consistency 植缺陷验证
# R version: 4.5.2 | packages: base only | set.seed(20260730)
# 敏感性分析：重新做尿酸分组（切点与主分析不一致）
dat$ua_q <- cut(dat$ua, breaks = c(-Inf, 300, 360, 420, Inf), right = FALSE,
                labels = c("Q1", "Q2", "Q3", "Q4"))
dat$age_band <- cut(dat$age, breaks = c(-Inf, 60, 70, Inf), right = TRUE,
                    labels = c("<60", "60-70", ">70"))
