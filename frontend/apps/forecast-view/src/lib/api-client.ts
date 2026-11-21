import { request } from '@shiro-mlops/shared/api'
import {
  PredictionRequest,
  PredictionResponse,
  PredictionResponseSchema,
} from '@/schemas/api'

export const apiClient = {
  async predict(params: PredictionRequest): Promise<PredictionResponse> {
    return request<PredictionResponse>(
      '/predict',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      PredictionResponseSchema,
    )
  },
}
