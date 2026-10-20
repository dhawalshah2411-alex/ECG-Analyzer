// ECG Analyzer - acquisition firmware
// Reads BioAmp EXG Pill output and streams samples over USB serial.
// Target board: Arduino UNO R4 Minima

const int   ECG_PIN       = A0;
const long  BAUD_RATE     = 115200;
const int   SAMPLE_RATE   = 500;                       // Hz
const long  SAMPLE_PERIOD = 1000000L / SAMPLE_RATE;    // microseconds
const long  MAX_LAG       = 10 * SAMPLE_PERIOD;        // 20 ms

unsigned long nextSampleTime = 0;

void setup() {
  Serial.begin(BAUD_RATE);
  analogReadResolution(14);
  nextSampleTime = micros();
}

void loop() {
  long lag = (long)(micros() - nextSampleTime);
  if (lag >= 0) {
    if (lag > MAX_LAG) {
      // Fell far behind - usually because the computer stopped reading
      // and sending got stuck. Restart the schedule from now instead of
      // sending every missed sample at full speed: that burst would
      // reach the app looking like real-time data.
      nextSampleTime = micros();
    }
    nextSampleTime += SAMPLE_PERIOD;
    int value = analogRead(ECG_PIN);
    Serial.println(value);
  }
}