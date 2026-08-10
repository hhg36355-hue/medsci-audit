# 测试夹具（非真实分析脚本），仅用于 check_binning_consistency 植缺陷验证
# R version: 4.5.2 | packages: base only | set.seed(20260730)
# 主分析：尿酸四分位分组
dat$ua_q <- cut(dat$ua, breaks = c(-Inf, 298, 356, 421, Inf), right = TRUE,
                labels = c("Q1", "Q2", "Q3", "Q4"))
dat$age_band <- cut(dat$age, breaks = c(-Inf, 60, 70, Inf), right = TRUE,
                    labels = c("<60", "60-70", ">70"))
