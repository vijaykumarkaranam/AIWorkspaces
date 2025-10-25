import axios, { AxiosInstance } from 'axios';
import { TopologyResponse } from '../types/topology';

class TopologyService {
  private api: AxiosInstance;

  constructor() {
    this.api = axios.create({
      baseURL: 'http://localhost:8080/api',
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    });
  }

  /**
   * Fetch topology data from backend
   */
  async getTopology(): Promise<TopologyResponse> {
    try {
      const response = await this.api.get<TopologyResponse>('/topology');
      return response.data;
    } catch (error) {
      console.error('Error fetching topology:', error);
      throw error;
    }
  }

  /**
   * Get list of available topologies
   */
  async getAvailableTopologies(): Promise<string[]> {
    try {
      const response = await this.api.get<string[]>('/topology/list');
      return response.data;
    } catch (error) {
      console.error('Error fetching available topologies:', error);
      throw error;
    }
  }

  /**
   * Check backend health
   */
  async checkHealth(): Promise<{ status: string; service: string; timestamp: string }> {
    try {
      const response = await this.api.get('/topology/health');
      return response.data;
    } catch (error) {
      console.error('Error checking health:', error);
      throw error;
    }
  }
}

export default new TopologyService();
