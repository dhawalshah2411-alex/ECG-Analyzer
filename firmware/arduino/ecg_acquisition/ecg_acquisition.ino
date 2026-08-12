// ECG Analyzer - acquisition firmware
// Reads BioAmp EXG Pill output and streams samples over USB serial.
// Target board: Arduino UNO R4 Minima

const int   ECG_PIN       = A0;
const long  BAUD_RATE     = 115200;
const int   SAMPLE_RATE   = 500;                    // Hz
const long  SAMPLE_PERIOD = 1000000L / SAMPLE_RATE; // microseconds

unsigned long nextSampleTime = 0;

void setup() {
  Serial.begin(BAUD_RATE);
  analogReadResolution(14);
  nextSampleTime = micros();
}

void loop() {
  if ((long)(micros() - nextSampleTime) >= 0) {
    nextSampleTime += SAMPLE_PERIOD;
    int value = analogRead(ECG_PIN);
    Serial.println(value);
  }
}