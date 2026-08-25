import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertCircle, CheckCircle2, ShieldCheck } from 'lucide-react'

const DRIFT_METRICS = [
  {
    feature: 'temperature_north (台北測站氣溫)',
    driftScore: 0.032,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'Wasserstein Distance',
  },
  {
    feature: 'relative_humidity (相對濕度)',
    driftScore: 0.048,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'Wasserstein Distance',
  },
  {
    feature: 'load_lag_24h (24小時前負載滯後)',
    driftScore: 0.088,
    threshold: 0.1,
    status: 'WARNING',
    statTest: 'PSI (Population Stability)',
  },
  {
    feature: 'load_rolling_mean_7d (7天滾動均值)',
    driftScore: 0.021,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'Wasserstein Distance',
  },
  {
    feature: 'is_weekend / is_holiday (假日指標)',
    driftScore: 0.005,
    threshold: 0.05,
    status: 'NORMAL',
    statTest: 'Chi-Square Test',
  },
]

export function DriftReportCard() {
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle className="text-base font-semibold text-slate-200 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-400" />
            Evidently AI 資料漂移即時監控報告 (Data Drift Summary)
          </CardTitle>
          <p className="text-xs text-slate-400 mt-1">
            基準資料集 (Training Set) vs 近 7 日推論特徵分佈檢驗
          </p>
        </div>
        <Badge variant="success" className="gap-1.5 py-1 px-3">
          <CheckCircle2 className="h-3.5 w-3.5" />
          整體資料分佈健康 (92% 無顯著漂移)
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="divide-y divide-slate-800/80">
          {DRIFT_METRICS.map((item, idx) => (
            <div
              key={idx}
              className="py-3.5 flex items-center justify-between text-xs"
            >
              <div className="space-y-1">
                <p className="font-mono font-semibold text-slate-200">
                  {item.feature}
                </p>
                <p className="text-[11px] text-slate-500">
                  檢定演算法：{item.statTest} ｜ 漂移門檻值：{item.threshold}
                </p>
              </div>

              <div className="flex items-center gap-4">
                <div className="text-right">
                  <span className="font-mono font-bold text-slate-200">
                    {item.driftScore.toFixed(3)}
                  </span>
                  <p className="text-[10px] text-slate-500">Drift Metric</p>
                </div>
                {item.status === 'NORMAL' ? (
                  <Badge variant="success" className="text-[10px]">
                    <CheckCircle2 className="h-3 w-3 mr-1" />
                    無漂移
                  </Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">
                    <AlertCircle className="h-3 w-3 mr-1" />
                    輕微偏離
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
